from xyz_motion import PlanningEnvironmentRos
from xyz_env_manager.client import get_planning_environment
from xyz_motion import AllRobotToolStatesRos,SE3,ToolRos,RobotRos,pose_to_list
from xyz_env_manager.client import get_all_robot_tool_states
from xyz_motion import RobotDriver
import copy,time,dill,math
from xyz_motion import CollisionChecker
from queue import PriorityQueue
import numpy as np
import tf.transformations as tfm
import threading
import concurrent.futures
from xyz_env_manager.msg import AttachedCollisionObject,Pose
from itertools import permutations
from xyz_depalletize_motion import utils

class Node:
   def __init__(self, value):
      self.value = value
      self.next = None
      
class Stack:
   def __init__(self):
      self.top = None

   def push(self, value):
      new_node = Node(value)
      new_node.next = self.top
      self.top = new_node

   def pop(self):
      if self.top is None:
         return None
      popped_value = self.top.value
      self.top = self.top.next
      return popped_value

   def is_empty(self):
      return self.top is None

class OBB:
   def __init__(self, center, half_size, angle):
      self.center = np.array(center)
      self.half_size = np.array(half_size)
      self.angle = angle
      self.axes = self.compute_axes()

   def compute_axes(self):
      cos_a = np.cos(self.angle)
      sin_a = np.sin(self.angle)
      u1 = np.array([cos_a, sin_a])      # 主轴（长边方向）
      u2 = np.array([-sin_a, cos_a])     # 副轴（短边方向）
      return u1, u2

   def get_corners(self):
      u1, u2 = self.axes
      corner1 = self.center + self.half_size[0] * u1 + self.half_size[1] * u2
      corner2 = self.center + self.half_size[0] * u1 - self.half_size[1] * u2
      corner3 = self.center - self.half_size[0] * u1 - self.half_size[1] * u2
      corner4 = self.center - self.half_size[0] * u1 + self.half_size[1] * u2
      return [corner1, corner2, corner3, corner4]

def project_obb(obb, axis):
   corners = obb.get_corners()
   projections = [np.dot(corner, axis) for corner in corners]
   return min(projections), max(projections)

def obb_overlap(obb1, obb2):
   axes = [obb1.axes[0], obb1.axes[1], obb2.axes[0], obb2.axes[1]]
   
   for axis in axes:
      min1, max1 = project_obb(obb1, axis)
      min2, max2 = project_obb(obb2, axis)
      
      if max1 < min2 or max2 < min1:
            return False    
   return True
 
def check_collision(our_robot,check_robot_list,planning_env,init_joints,container_item):
   #获取当前抓取箱子坐标
   tf_map_object = SE3(pose_to_list(container_item.origin))
   tf_map_object = tf_map_object*SE3([0,0,-0.035,0,0,0,1])
   #获取抓取法兰所有姿态
   tf_tip_object_list = [[0,0,0,1,0,0,0],[0,0,0,0,1,0,0]]   
   tf_map_flange_list = []
   for tf_tip_object in tf_tip_object_list:
      tf_tip_object = SE3(tf_tip_object)
      tf_map_flange = tf_map_object * tf_tip_object.inv() * our_robot.get_active_tool().get_tf_endflange_tip("tip_0").inv()
      tf_map_flange_list.append(tf_map_flange.xyz_quat)   
     
   kinematic_solver = our_robot.get_kinematics_solver()

   #计算所有抓取姿态法兰joint
   check_joints = []
   init_jonints_list = []
   init_joints = [0.0, -1.57, 1.4, 0.0]
   init_jonints_list.append(init_joints)
   init_jonints_list.append(init_joints[0:-1]+[init_joints[-1]+3.1415926])
   init_jonints_list.append(init_joints[0:-1]+[init_joints[-1]-3.1415926])
   for i in tf_map_flange_list:
      for init_joint in init_jonints_list:
         check_joint = kinematic_solver.compute_best_ik(SE3(i), init_joint)
         if not check_joint:
            check_joint = kinematic_solver.compute_best_ik(SE3(i), init_joint)
         else:
            if len(check_joint)==4:
               check_joint = kinematic_solver.convert_four_dof_to_six(check_joint)
               check_joints.append(check_joint) 
               break
            else:  
               check_joints.append(check_joint) 
               break 
      if not check_joints:                
         return True   
                

   #检测所有的姿态是否满足气缸碰撞条件，如果满足只取一组解
   collision_flag = True
   for joint_index,check_joint in enumerate(check_joints):
      for check_robot in check_robot_list:
         #添加碰撞检测器
         checker = CollisionChecker(check_robot, planning_env)   
         if checker.check_point_collision(check_joint):
            if container_item.additional_info.values[-3]=="28":
               pass
               #import ipdb;ipdb.set_trace()
            continue
         else:
            if container_item.additional_info.values[-3]=="24":
               pass
               #import ipdb;ipdb.set_trace()
            collision_flag = False   
            break       
   return collision_flag




#过滤得到顶层箱子
def filter_layer_items(items,row_flag=True):
   #两种模式,一种只取最高层，另一种则是每列箱子的最高层
   if row_flag:
      combined_data = {}
      for item in items:
         #建立x,y坐标的键，同一列箱子xy坐标一致
         key = (round(item.origin.x,2), round(item.origin.y,2))
         if key not in combined_data.keys():
            #判断原先字典是否有xy近似的key的标志flag
            check_key_flag = False
            for check_key in combined_data.keys():
               #判断绝对值是否小于0.015，如果xy都小于0.015，则认为是同列箱子
               if abs(item.origin.x-check_key[0])<0.015 and abs(item.origin.y-check_key[1])<0.015:    
                  check_key_flag = True
                  break      
                #如果不存在标志,则说明是个新列                   
            if not check_key_flag:                    
               combined_data[key] = item
            #如果存在,则说明是老列,则需要判断是否保留z最大的实例   
            else:
               if item.origin.z > combined_data[check_key].origin.z:
                  combined_data[check_key] = item        
         else:   
            # 只保留Z最大的类实例
            if item.origin.z > combined_data[key].origin.z:
               combined_data[key] = item

      new_items = list(combined_data.values())
        
   #只考虑最高列,不考虑每列层数不同   
   else:
      max_z = max(i.origin.z for i in items)
      new_items = list(filter(lambda x:abs(x.origin.z-max_z)<0.1,items))
   return new_items



#过滤得到底层箱子
def filter_bottom_items(items,row_flag=True):
   #两种模式,一种只取最低层，另一种则是每列箱子的最低层
   if row_flag:
      combined_data = {}
      for item in items:
         #建立x,y坐标的键，同一列箱子xy坐标一致
         key = (round(item.origin.x,2), round(item.origin.y,2))
         if key not in combined_data.keys():
            #判断原先字典是否有xy近似的key的标志flag
            check_key_flag = False
            for check_key in combined_data.keys():
               #判断绝对值是否小于0.015，如果xy都小于0.015，则认为是同列箱子
               if abs(item.origin.x-check_key[0])<0.015 and abs(item.origin.y-check_key[1])<0.015:    
                  check_key_flag = True
                  break
            #如果不存在标志,则说明是个新列         
            if not check_key_flag:                    
               combined_data[key] = item
            #如果存在,则说明是老列,则需要判断是否保留z最小的实例   
            else:
               if item.origin.z < combined_data[check_key].origin.z:
                  combined_data[check_key] = item                  
         else:   
            # 只保留Z最小的类实例
            if item.origin.z < combined_data[key].origin.z:
               combined_data[key] = item

      new_items = list(combined_data.values())
   #只考虑最低列,不考虑每列层数不同      
   else:    
      min_z = min(i.origin.z for i in items)
      new_items = list(filter(lambda x:abs(x.origin.z-min_z)<0.1,items))    
   return new_items

class CostItem:

   def __init__(self, f_cost,g_cost,current_node,state_key,parent=None):
      self.f_cost = f_cost
      self.g_cost = g_cost
      self.current_node = current_node
      self.state_key = state_key 
      self.parent = parent
   def __lt__(self, other):
      return self.f_cost < other.f_cost

   # 从当前节点逆向回溯以重建路径
   def reconstruct_path(self):
      path = []
      current = self
      while current:
         path.insert(0, current.current_node.additional_info.values[-3])
         current = current.parent
      return path
   
"""

A*算法,总代价=实际代价+预估的启发式代价，从而优先搜索具有更低总代价的节点

""" 

class A_STAR():

   def __init__(self) -> None:

      #缓存来存储已计算的启发式代价
      self.heuristic_cache = {}

      # 初始化一个字典用于存储已访问的状态
      self.visited_states = {}
      # 日志
      self.logger = None

      self.xtf = None

   #用于实际代价
   def g_current_cost(self,start_node, target_node):
      """
      当前代价代价函数

      Parameters:
      - start_node: 起始点
      - target_node: 目标点

      Returns:
      返回一个代价值cost
      """  
      dx = abs(start_node.origin.x - target_node.origin.x)
      dy = abs(start_node.origin.y - target_node.origin.y)
      dz = abs(start_node.origin.z - target_node.origin.z)

      return dx + dy + dz

   #需要根据垛型去计算当前节点到预估点的代价，目前暂时不太好一种算法计算不同垛型
   def heuristic_cost_estimate(self,start_node, target_node):
      """
      启发式代价函数

      Parameters:
      - start_node: 起始点
      - target_node: 目标点

      Returns:
      返回一个代价值cost
      """   
      start_node_id = int(start_node.additional_info.values[-3])
      target_node_id = int(target_node.additional_info.values[-3])
      #通过哈希表记录每次代价计算如果存在已计算过的，直接获取
      if (start_node_id, target_node_id) in self.heuristic_cache:
         return self.heuristic_cache[(start_node_id, target_node_id)]  

      #对角线距离

      dx = abs(start_node.origin.x - target_node.origin.x)
      dy = abs(start_node.origin.y - target_node.origin.y)
      dz = abs(start_node.origin.z - target_node.origin.z)

      # 在水平、垂直和垂直方向上的移动成本
      diagonal_cost = min(dx, dy, dz)

      # 剩余移动成本
      remaining_cost = abs(dx - dy) + abs(dy - dz) + abs(dz - dx)

      # 计算总成本
      total_cost = int(diagonal_cost * math.sqrt(3) + remaining_cost)

         
      # 将计算结果放入缓存
      self.heuristic_cache[(start_node_id, target_node_id)] = total_cost

      return total_cost
   
   def check_collision(self,our_robot,check_robot_list,planning_env,init_joints,container_item,stop_event):
      #获取当前抓取箱子坐标
      tf_pick_object = SE3(pose_to_list(container_item.origin))

      #获取抓取法兰所有姿态
      tf_tip_object_list = [[0,0,0,1,0,0,0],[0,0,0,0,1,0,0]]   
      tf_map_flange_list = []
      for tf_tip_object in tf_tip_object_list:
         tf_map_flange_dict = {}
         tf_tip_object = SE3(tf_tip_object)
         #抓取点
         tf_pick_flange = tf_pick_object * tf_tip_object.inv() * our_robot.get_active_tool().get_tf_endflange_tip("tip_0").inv()
         tf_map_flange_dict["pick"] = tf_pick_flange.xyz_quat
         tf_map_flange_list.append(tf_map_flange_dict)
      
      kinematic_solver = our_robot.get_kinematics_solver()

      #计算所有抓取姿态法兰joint
      check_joints = []
      init_joints_list = []
      init_joints_list.append(init_joints)
      init_joints_list.append(init_joints[0:-1]+[init_joints[-1]+3.1415926])
      init_joints_list.append(init_joints[0:-1]+[init_joints[-1]-3.1415926])
      for tf_map_flange_dict in tf_map_flange_list:
         if stop_event.is_set():
            return True
         for init_joint in init_joints_list:
            if stop_event.is_set():
               return True
            check_joint = kinematic_solver.compute_best_ik(SE3(tf_map_flange_dict["pick"]), init_joint)
            if not check_joint:
               check_joint = kinematic_solver.compute_best_ik(SE3(tf_map_flange_dict["pick"]), init_joint)
            else:
               if len(check_joint)==4:
                  check_joint = kinematic_solver.convert_four_dof_to_six(check_joint)
                  check_joints.append(check_joint) 
                  break
               else:  
                  check_joints.append(check_joint) 
                  break 
         if not check_joints:                
            return True   
                  

      #检测所有的姿态是否满足气缸碰撞条件，如果满足只取一组解
      collision_flag = True
      for joint_index,check_joint in enumerate(check_joints):
         for check_robot in check_robot_list:
            #添加碰撞检测器
            checker = CollisionChecker(check_robot, planning_env)   
            if checker.check_point_collision(check_joint):
               if container_item.additional_info.values[-3]=="9":
                  pass
                  #import ipdb;ipdb.set_trace()
               continue
            else:
               collision_flag = False   
               break      

      return collision_flag
   def check_all_collisions(self,our_robot, check_robot_list, planning_env, 
                            init_joints, next_item,open_set,state_key,target_item,current_node,retrieved_item,g_cost,open_set_lock,stop_event):
      try:
         #节点ID到路径里
         new_state_key = state_key + [next_item.name]
         # 判断箱子是否干涉
         if not self.check_collision(our_robot, check_robot_list, planning_env, init_joints, next_item,stop_event):
            # 计算总代价

            #计算预估代价
            h_cost = self.heuristic_cost_estimate(next_item, target_item)
            #更新当前g(n)代价
            g_cost = self.g_current_cost(current_node,next_item)+g_cost
            #更新将f(n)代价
            f_cost = g_cost + h_cost

            # 将f(n)代价，当前代价g(n)，当前节点，路径ID,环境,箱子放入队列
            cost_item = CostItem(f_cost,g_cost,next_item,new_state_key,retrieved_item)  
            with open_set_lock:
               open_set.put(cost_item) 
         return True 
      except:
            if stop_event.is_set():
               self.logger(f"stop_event")   
            else:   
               self.logger(f"error")    
            return False       
                                
   def path_check(self,path,container_items,our_robot,check_robot_list,planning_env,init_joints,stop_event):
      #偏置列表
      slide_list = [[0.08, 0.08, 0.1, 0, 0, 0, 1], [0.08, -0.08, 0.1, 0, 0, 0, 1], [-0.08, 0.08, 0.1, 0, 0, 0, 1], [-0.08, -0.08, 0.1, 0, 0, 0, 1]]
      # 遍历路径
      self.logger(f"开始后验路径{path}")
      for node in path:
         self.logger(f"后验节点{node}")
         #获取当前节点箱子
         pick_item = list(filter(lambda x: x.additional_info.values[-3] == node, container_items))
         if len(pick_item)!=1:
            self.logger(f"后验检查,{node}不在容器中")
            return False        
         pick_item = pick_item[0]
         planning_env.clear_container_items("0", [pick_item.name])
         attached_collision_object = AttachedCollisionObject()
         attached_collision_object.reference_tip_name = 'tip_0'
         attached_collision_object.reference_object_name = pick_item.name
         attached_collision_object.objects = [pick_item]
         attached_collision_object.from_workspace_id = "0"
         attached_collision_object.to_workspace_id = "1"
         attached_collision_object.origin_tip_transform = Pose(0,0,0,1,0,0,0)
         our_robot.detach_object()
         our_robot.attach_object(attached_collision_object,[])
         for check_robot in check_robot_list:
            check_robot.detach_object()  
            check_robot.attach_object(attached_collision_object,[])          
         
         #拆分xy偏移精度
         def split_slide(slide,precision):
            split_x_length = int(slide[0]/precision)
            split_y_length = int(slide[1]/precision)
            new_slide_x = []
            new_slide_y = []
            for i in range(1,abs(split_x_length)+1):
               if split_x_length>0:
                  if i*precision>=0.014:
                     new_slide_x.append(i*precision)
               else:
                  if -i*precision<=-0.014:
                     new_slide_x.append(-i*precision)        
            for i in range(1,abs(split_y_length)+1):
               if split_y_length>0:
                  if i*precision>=0.014:
                     new_slide_y.append(i*precision)
               else:
                  if -i*precision<=-0.014:
                     new_slide_y.append(-i*precision)   
            return_list = [[x,y]+slide[2:7] for x,y in zip(new_slide_x,new_slide_y)]                               
            return return_list  
         
         def divide_float_into_list(value, precision):
            # 计算需要多少步骤来从0达到目标值，加1是为了包含最终值本身
            steps = int(value / precision) + 1
            # 生成列表，使用round确保浮点数精度问题不会影响结果
            result = [round(i * precision, 2) for i in range(1, steps)]
            return result 
                                   
         #遍历偏置列表
         slide_flag = False
         for slide in slide_list:
            #xy偏移拆分精度
            precision = 0.001
            check_offset_xy_list = split_slide(slide,precision)
            self.logger(f"check_offset_xy_list is {check_offset_xy_list}")
            xy_check_collision = False
            for check_slide_xy in check_offset_xy_list:
               #更新偏移
               check_item = copy.deepcopy(pick_item)
               check_item.origin = Pose(*((SE3(check_slide_xy)*SE3(pose_to_list(check_item.origin))).xyz_quat))
               if self.check_collision(our_robot,check_robot_list,planning_env,init_joints,check_item,stop_event):
                  self.logger(f"后验xy拆分{check_slide_xy}检测到碰撞")
                  xy_check_collision = True
                  break
               else:
                  continue
            if xy_check_collision:
               self.logger(f"偏移点{slide}在XY方向上检测到碰撞")   
               continue
            else:                                  
               #如果xy偏置无干涉,开始后验z方向的偏置   
               #z方向偏移拆分精度
               offset_z = slide[2]+0.23
               z_precision = 0.03
               offset_list = divide_float_into_list(offset_z,z_precision)
               self.logger(f"offset_list为{offset_list}")
               offset_check_slide_list = []
               for offset in offset_list:
                  append_check_slide = copy.deepcopy(slide)
                  append_check_slide[2] = offset 
                  offset_check_slide_list.append(append_check_slide)    
               self.logger(f"检查偏移点向上偏移,偏移列表为{offset_check_slide_list}")      
               z_check_collision = False    
               for check_slide_z in offset_check_slide_list:  
                  #更新偏移
                  check_item = copy.deepcopy(pick_item)
                  check_item.origin = Pose(*((SE3(check_slide_z)*SE3(pose_to_list(check_item.origin))).xyz_quat))
                  check_item.origin.z+=0.035                     
                  if self.check_collision(our_robot,check_robot_list,planning_env,init_joints,check_item,stop_event):
                     self.logger(f"后验z拆分{check_slide_z}检测到碰撞")
                     z_check_collision = True
                     break     
                  else:
                     continue     
               if z_check_collision:
                  self.logger(f"偏移点{slide}在Z方向上检测到碰撞")   
                  continue     
               else:   
                  self.logger(f"偏移点{slide}XYZ后验无碰撞")
                  slide_flag = True
                  break
                                                      
         if slide_flag:
            self.logger(f"{node}验证ok,偏置{slide}无碰撞,继续搜索")
            continue
         else:
            self.logger(f"{node}验证失败")
            our_robot.detach_object()   
            for check_robot in check_robot_list:
               check_robot.detach_object()              
            return False 
         
      our_robot.detach_object()   
      for check_robot in check_robot_list:
         check_robot.detach_object()                    
      return True

   def a_star_search(self,our_robot, check_robot_list, planning_env, init_joints,\
                           container_items,filtered_items,target_item):
      """
      A* 路径搜索算法:f(n) = g(n) + h(n)
      Parameters:
      - our_robot: 初始的robot,用于得到tip、tool等数据
      - check_robot_list: 一个用于计算碰撞的robot列表
      - planning_env: 环境，用于反复操作
      - init_joints: 机器人初始点位，用于求解抓取点
      - container_items: 当前环境的箱子
      - filtered_items: 一开始可以抓的解，也就是起始点
      - target_item:目标箱子

      Returns:
      返回一个列表，列表按抓取顺序排列
      """


      # 初始化优先队列
      open_set = PriorityQueue() 


      # 初始化标志变量
      found_shortest_path = False

      # copy了一份初始解的环境，便于后续环境里箱子的操作
      init_planning_env = copy.copy(planning_env)

      # 预先计算所有可能的起始点到目标点的代价
      for init_node in filtered_items:
         h_cost = self.heuristic_cost_estimate(init_node,target_item)
         f_cost = h_cost+0
         init_node_id = init_node.additional_info.values[-3]
         cost_item = CostItem(f_cost,0,init_node,[init_node.name])    
         open_set.put(cost_item)  

      # 创建一个锁
      open_set_lock = threading.Lock()
      # 创建一个停止事件
      stop_event = threading.Event()

      self.logger(f"拣配算法开始计算")

      with concurrent.futures.ThreadPoolExecutor() as executor:
         # 进入优先队列的循环,队列不为空就一直循环   
         while not found_shortest_path and not self.xtf.preempted:
            try:            
               # 取出所有的栈数据
               retrieved_item = open_set.get(timeout=5)
               f_cost = retrieved_item.f_cost
               g_cost = retrieved_item.g_cost
               current_node = retrieved_item.current_node
               state_key = retrieved_item.state_key

               # 初始化环境
               planning_env = copy.copy(init_planning_env)
               # 清除当前路径下箱子的环境
               planning_env.clear_container_items("0", [name for name in state_key])

               # 如果箱子在目标箱子里，则添加到所有路径里
               if not self.check_collision(our_robot, check_robot_list, planning_env, init_joints, target_item,stop_event):
                  # 搜索结束，回溯路径
                  path = retrieved_item.reconstruct_path()
                  # 设置标志变量，告知找到最短路径
                  # found_shortest_path = True
                  # stop_event.set()
                  # break
                  planning_env = copy.copy(init_planning_env)
                  if self.path_check(path,container_items,our_robot,check_robot_list,planning_env,init_joints,stop_event):
                     # 设置标志变量，告知找到最短路径
                     found_shortest_path = True
                     stop_event.set()
                     break
                  else:
                     self.logger(f"已搜索到路径,但是路径不可行,重新搜索")
                     path = []
                     continue

               #将路径节点ID当成键值
               current_state_key = tuple(sorted(state_key))
               # 判断是否已经访问过这个状态
               if current_state_key in self.visited_states:          
                  continue   

               # 将当前状态添加到已访问的字典中
               self.visited_states[current_state_key] = current_node.name

               # 过滤掉已搜索路径的箱子
               remaining_items = list(filter(lambda x: x.name not in [name for name in state_key], container_items))
               # 过滤非顶层箱子
               remaining_items = filter_layer_items(remaining_items)


               # 搜索剩余可抓箱子是否与环境干涉
               for next_item in remaining_items:
                  executor.submit(self.check_all_collisions, our_robot, check_robot_list, planning_env, 
                  init_joints, next_item,open_set,state_key,target_item,current_node,retrieved_item,g_cost,open_set_lock,stop_event)
            except Exception as e:
               self.logger(f"异常为{e}")
               self.logger(f"拣配算法未搜索到路径")
               path = []
               break   
         # 关闭线程池，不再接受新任务
         executor.shutdown(wait=True)   
         open_set.task_done()  
      calculation_dict = {}
      if not path:
         self.logger(f"拣配计算终止")
         return calculation_dict
      else:   
         self.logger(f"拣配计算得到{path}")
         calculation_dict["path"] = path   
         return calculation_dict
           

def execute(self, inputs, outputs, gvm):
   self.logger.info("Hello {}".format(self.name))
   row = gvm.get_variable("row", per_reference=False, default=None)
   seach_current_time = time.time()
   if not gvm.get_variable("motion_payload", per_reference=True, default=None):
      planning_env_msg = get_planning_environment()
      planning_env = PlanningEnvironmentRos.from_ros_msg(planning_env_msg)
   else:
      last_payload = gvm.get_variable("motion_payload", per_reference=True, default=None)
      planning_env = PlanningEnvironmentRos.from_ros_msg(last_payload["planning_environment"])
      

   #计算所有抓取姿态法兰joint
   q0 = inputs["q0"]
   if q0:
      init_joints = q0
   else:
      self.logger.info("未收到input q0 通过机器人获取实时init joint")
      r = RobotDriver(0)
      init_joints = list(r.get_joints()) 

   all_robot_states = AllRobotToolStatesRos.from_ros_msg(get_all_robot_tool_states()) 
   our_robot = all_robot_states.get_robot_ros("0")
   our_robot.detach_object()      
   #得到初始的夹具 
   robot_tool_state = all_robot_states.get_robot_tool_state("0")
   tool_name = robot_tool_state.tool_name
   init_cur_tool = all_robot_states.get_tool_ros(tool_name).to_ros_msg()   

   #通过碰撞体名字找到对应碰撞体
   init_tool_collisions = []
   init_clamp_collision = []
   tool_check_collision_list = ["+y","-y","x"]
   for i in init_cur_tool.tool_collisions_list:
      if i.name in tool_check_collision_list:
         init_tool_collisions.append(i)
      else:
         init_clamp_collision.append(i)  
         
   #相机扩大一点
   for i in init_clamp_collision:
      if i.name == "camera":
         i.primitives[0].dimensions = [0.6, 0.33+0.05, 0.25+0.05] 
      if i.name == "body":
         i.primitives[0].dimensions = [0.388, 0.588, 0.65]  

   #共有 x+y和x-y的两种our robot    
   check_robot_list = []   
   
   #x,+y our robot
   check_our_robot = all_robot_states.get_robot_ros("0") 
   check_our_robot.detach_object()   
   check_our_robot_msg = check_our_robot.to_ros_msg()

   #添加默认就有的干涉物，像相机，夹具本体
   check_our_robot_msg.tool.tool_collisions.primitives=[i.primitives[0] for i in init_clamp_collision] 

   #添加可活动气缸
   for index,clamp_collision in enumerate(init_tool_collisions):
      if clamp_collision.name =="x":
         check_our_robot_msg.tool.tool_collisions.primitives.append(clamp_collision.primitives[0])
      if clamp_collision.name == "+y":
         check_our_robot_msg.tool.tool_collisions.primitives.append(clamp_collision.primitives[0])

   #因为our robot 不能用copy模块序列化，所以需要从新序列化        
   check_robot_list.append(RobotRos.from_ros_msg(check_our_robot_msg))

   #x,-y our robot
   check_our_robot = all_robot_states.get_robot_ros("0") 
   check_our_robot.detach_object()   
   check_our_robot_msg = check_our_robot.to_ros_msg()
   #添加默认就有的干涉物，像相机，夹具本体
         
   check_our_robot_msg.tool.tool_collisions.primitives=[i.primitives[0] for i in init_clamp_collision] 
   #添加可活动气缸
   for index,clamp_collision in enumerate(init_tool_collisions):
      if clamp_collision.name =="x":
         check_our_robot_msg.tool.tool_collisions.primitives.append(clamp_collision.primitives[0])
      if clamp_collision.name == "-y":
         check_our_robot_msg.tool.tool_collisions.primitives.append(clamp_collision.primitives[0])

   #因为our robot 不能用copy模块序列化，所以需要从新序列化        
   check_robot_list.append(RobotRos.from_ros_msg(check_our_robot_msg))



   #获取来料位放置规划的箱子  
   pick_ws_id = inputs["pick_id"]
   plan_items = planning_env.get_unfinished_planned_items(pick_ws_id)     
   #获取来料上已有的箱子
   container_items = planning_env.get_container_items(pick_ws_id)  

   #得到放置规划碰撞的箱子
   filter_check_collision_plan = lambda container_item: check_collision(our_robot, check_robot_list,planning_env, init_joints, container_item)
   collision_items = list(filter(filter_check_collision_plan, plan_items))  
   if len(collision_items):
      self.logger.info(f"当前已有箱子无法合并为满托,存在{[i.additional_info.values[-3] for i in collision_items]}放置干涉")
      #得到已有箱子抓取的起始点
      filter_check_collision_container = lambda container_item: not check_collision(our_robot, check_robot_list,planning_env, init_joints, container_item)
      # 过滤已有箱子非顶层箱子
      filtered_items = filter_layer_items(container_items)
      filtered_items = list(filter(filter_check_collision_container, filtered_items))  

      #将放置碰撞的箱子当做计算的目标箱子
      collision_items = filter_bottom_items(collision_items,False)
      target_item = collision_items[0]
      
      #添加函数参数       
      async_input = (our_robot, check_robot_list, planning_env, init_joints, \
                     container_items, filtered_items, target_item)

      #启动计算
      a_star = A_STAR()
      a_star.logger = self.logger.info
      a_star.xtf = self

      calculation_dict = a_star.a_star_search(*async_input)

      #得到路径   
      merge_pick_path = calculation_dict["path"] 
            
      #路径
      if not merge_pick_path:
         self.logger.info(f"没有找到可以抓取到目标物无碰撞的路径解")
         raise Exception("当前路径所有箱子已遍历,但仍未找到目标点,是个bug")
         
      self.logger.info(merge_pick_path)

      outputs["merge_pick_path"] = merge_pick_path
      gvm.set_variable("merge_pick_path", merge_pick_path, per_reference=False)
      self.logger.info(f"search time is {time.time()-seach_current_time}")

      return "clear_collision"
   else:
      self.logger.info(f"来料托盘上的物料使用拣配算法可以合并为满托")
      #新增算法完善多拆箱子的路径解,主要问题是因为原先靠拣配的算法,导致拆箱子的路径解不完整,所以需要额外算法补全
      #大概思路是采用从底层到高层逐步求解,将每一层放置方式遍历,求出共同干涉的箱子
      
      #通过obb计算是否碰撞
      def is_collision_slide(init_check_plan_item,other_plan_items):
         #通过移动单个规划的箱子,检测这个箱子是否可以放置
         check_slide = [
               [0.05,0.05],
               [0.05,-0.05],
               [-0.05,0.05],
               [-0.05,-0.05]
            ]
         is_collision_flag = True
         #偏置箱子并检测是否碰撞
         for slide in check_slide:
            check_plan_item = copy.deepcopy(init_check_plan_item)
            check_plan_item.origin.x += slide[0]
            check_plan_item.origin.y += slide[1]
            
            check_item_pose = pose_to_list(check_plan_item.origin)
            l_1,w_1,h_1 = check_plan_item.primitives[0].dimensions
            check_item_angle = tfm.euler_from_quaternion(check_item_pose[3:7])[2]
            check_item_obb = OBB(center=(check_item_pose[0], check_item_pose[1]), half_size=(l_1/2-0.01,w_1/2-0.01), angle=check_item_angle)
            
            check_collision = False
            for plan_item in other_plan_items:
               item_pose = pose_to_list(plan_item.origin)
               l_2,w_2,h_2 = plan_item.primitives[0].dimensions
               item_angle = tfm.euler_from_quaternion(item_pose[3:7])[2]
               item_obb = OBB(center=(item_pose[0], item_pose[1]), half_size=(l_2/2-0.01,w_2/2-0.01), angle=item_angle)
               
               if not obb_overlap(check_item_obb,item_obb):
                  check_collision = False
                  continue
               else:
                  check_collision = True
                  break  
            #如果偏置点干涉,继续下一个偏置检测,不干涉直接返回结果    
            if check_collision:
               continue
            else:
               is_collision_flag = False
                        
         return is_collision_flag  
                 
      #检查一层的箱子是否可以合并
      def find_layer_full_collision(self,workspace,layer_plan_items,layer_container_items):
         vertices = utils.get_box_vertices(
         workspace.get_bottom_pose().xyz_quat + workspace.get_dimensions())
         # 续码任务需要根据剩余的slot来调整place corner id, 否则会存在无法码满的情况
         slot_center = np.mean([[pose_to_list(s.origin)[0], pose_to_list(s.origin)[1]] for s in layer_plan_items], axis=0)
         distance_list = np.array([np.linalg.norm(slot_center - np.array(place_vertice[0:2])) for place_vertice in vertices[:4]])
         indices = np.where(abs(distance_list-max(distance_list))<1e-3)[0]
         place_corner_id = indices[0]
         target_vertex = vertices[place_corner_id]
         #先按照角点排序规划箱子  
         def sort_by_corner(layer_plan_items):
            return np.mean(np.array([np.linalg.norm(np.array([obj.origin.x, obj.origin.y]) -
            np.array(target_vertex[:2])) for obj in layer_plan_items]))    
         layer_plan_items = sorted(layer_plan_items,key=lambda x:sort_by_corner([x]))   
          
         #check_plan_items_list 是一层放置规划的排列组合
         update_plan_items = []
         for plan_item in layer_plan_items:
            plan_item_id = plan_item.additional_info.values[-3]
            #去除当前规划箱子
            check_layer_plan_items = copy.deepcopy(layer_plan_items)
            [check_layer_plan_items.remove(i) for i in update_plan_items]
            
            #通过移动单个规划的箱子,检测这个箱子是否可以放置
            #如果箱子无法放置,则计算拿走哪些现有的箱子后不会干涉
            collision_path = []
            if is_collision_slide(plan_item,update_plan_items+layer_container_items):  
               self.logger.info(f"检测到规划箱子{plan_item_id}偏移干涉,准备计算拿走哪个箱子会不干涉")    
               stack = Stack()
               stack.push([plan_item,layer_container_items,collision_path])
               
               while not stack.is_empty() and not self.preempted:
                  init_collision_item, old_container_items,collision_path = stack.pop() 
                  
                  #遍历拿走哪个真实箱子不会干涉
                  for container_item in old_container_items:
                     check_container_items = copy.deepcopy(old_container_items)
                     check_container_items.remove(container_item)
                     
                     #检测拿走真实箱子后,判断规划箱子是否碰撞
                     if not is_collision_slide(init_collision_item,collision_path+check_container_items+update_plan_items):  
                        collision_path.append(container_item)    
                                       
                        #如果拿走真实箱子后不干涉,则计算拿走的真实箱子本身是否干涉   
                        if is_collision_slide(container_item,update_plan_items+check_container_items):  
                           stack.push([container_item,check_container_items,collision_path])   
                        else:
                           collision_path_id_list = [i.additional_info.values[-3] for i in collision_path]
                           self.logger.info(f"检测到规划箱子{plan_item_id}需要拿走箱子{collision_path_id_list}才能放置") 
                           return collision_path_id_list,True
               if stack.is_empty():
                  self.logger.info(f"栈数据为空,检测到规划箱子{plan_item_id}干涉,但是遍历所有真实的箱子后无法让它不干涉")
                  return [],True
            else:
               self.logger.info(f"规划箱子{plan_item_id}无干涉,准备计算下一个箱子")   
               update_plan_items.append(plan_item)
               continue
         
         return [],False    
               
         
      for layer in range(0,7):
         self.logger.info(f"开始计算第{layer+1}层") 
         box_id_list = [str(i+layer*row) for i in range(1,row+1)] 
         layer_plan_items = list(filter(lambda x: x.additional_info.values[-3] in box_id_list, plan_items))
         layer_container_items = list(filter(lambda x: x.additional_info.values[-3] in box_id_list, container_items))
         if len(layer_container_items)==row:
            self.logger.info(f"第{layer+1}层实际为满箱,跳过计算")
            continue
         if not len(layer_container_items) and len(layer_plan_items)==row:
            self.logger.info(f"第{layer+1}层无实际箱子,规划箱子也为满,终止检测")
            break
         workspace = planning_env.get_workspace_ros("0")
         collision_path_id_list,result_flag = find_layer_full_collision(self,workspace,layer_plan_items,layer_container_items)
         if result_flag:
            if not collision_path_id_list:
               self.logger.info(f"排序计算存在干涉,但是不管如何计算都无法解除干涉")
               raise Exception(f"排序计算存在干涉,但是不管如何计算都无法解除干涉")
            else:
               self.logger.info(f"排序计算存在干涉,计算路径为{collision_path_id_list}")         
               #通过平层排序计算,调用拣配算法接口,从而得到多拆的路径
               #得到已有箱子抓取的起始点
               filter_check_collision_container = lambda container_item: not check_collision(our_robot, check_robot_list,planning_env, init_joints, container_item)
               # 过滤已有箱子非顶层箱子
               filtered_items = filter_layer_items(container_items)
               filtered_items = list(filter(filter_check_collision_container, filtered_items))  

               #将放置碰撞的箱子当做计算的目标箱子
               target_items = list(filter(lambda x:x.additional_info.values[-3]==collision_path_id_list[-1],container_items))
               target_item = target_items[0]
               
               #添加函数参数       
               async_input = (our_robot, check_robot_list, planning_env, init_joints, \
                              container_items, filtered_items, target_item)

               #启动计算
               a_star = A_STAR()
               a_star.logger = self.logger.info
               a_star.xtf = self

               calculation_dict = a_star.a_star_search(*async_input)

               #得到路径   
               merge_pick_path = calculation_dict["path"] 
                     
               #路径
               if not merge_pick_path:
                  self.logger.info(f"没有找到可以抓取到目标物无碰撞的路径解")
                  raise Exception("当前路径所有箱子已遍历,但仍未找到目标点,是个bug")
                  
               self.logger.info(merge_pick_path)

               outputs["merge_pick_path"] = merge_pick_path
               gvm.set_variable("merge_pick_path", merge_pick_path, per_reference=False)
               self.logger.info(f"search time is {time.time()-seach_current_time}")               
               
               return "clear_collision"
         else:
            self.logger.info(f"第{layer+1}层排序计算不存在干涉")
      self.logger.info(f"排序计算无干涉,不需要多拆箱子")      
      return "success"

