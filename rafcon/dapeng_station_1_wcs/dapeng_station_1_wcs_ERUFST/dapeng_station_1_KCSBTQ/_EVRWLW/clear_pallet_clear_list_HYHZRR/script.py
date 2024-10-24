import requests
import json
from rafcon.xyz_exception_base import XYZExceptionBase


def execute(self, inputs, outputs, gvm):
    """ 
    Report current task finish to wcs.

    Args:
        Inputs Data:
            None

        Outputs Data:
            None

        Gvm: 
            None
            
    Properties Data:
        comment, (unicode): Default value (u"from_extern_service").
            The comment of this state. This will show in state's GUI block.

        task_id: the id of the current task

    Outcomes:
        0: success
        -1: aborted
        -2: preempted
    """
    self.logger.info("Running {}({})({})".format(self.name, self.unique_id, self.smart_data["comment"]))

    url = "http://127.0.0.1:7002/api/rafcon/clear_pallet_clear_list"
    data = {
        "pallet_clear_list":[]
        }
    try: 
        response = requests.post(url, json = data).json()
    except requests.exceptions.ConnectionError as e:
        raise Exception("Connection Error: {}".format(e))
    except: 
        raise Exception("Unknown errors occured when requesting response from hmi-back.")
    self.logger.info(response)
    return "success"
