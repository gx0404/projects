"""V1.4.0: 修改路由, 指定项目类型

Revision ID: 287e8b3869da
Revises: 710f9f74eedb
Create Date: 2022-09-07 16:05:01.470132

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '287e8b3869da'
down_revision = '710f9f74eedb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("UPDATE routes SET project_type='DPT' where id = 5;")
    op.execute("UPDATE routes SET path='history-info', project_type='PP', name='HEADER.HISTORY_INFO' where id = 6;")
    op.execute("INSERT INTO routes VALUES (7, 'custom', 'DPT', 'HEADER.CUSTOM'), (8, 'custom', 'PP', 'HEADER.CUSTOM');")
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("DELETE FROM routes WHERE id in (7,8);")
    op.execute("UPDATE routes SET project_type=NULL where id = 5;")
    op.execute("UPDATE routes SET path='custom', project_type=NULL, name='HEADER.CUSTOM' where id = 6;")
    # ### end Alembic commands ###
