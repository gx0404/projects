"""V1.4.0: 修改路由记录 history-info -> task-history

Revision ID: 710f9f74eedb
Revises: bcd63de5b3ab
Create Date: 2022-08-31 09:57:54.395711

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '710f9f74eedb'
down_revision = 'bcd63de5b3ab'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("update routes set path = 'history-info', name = 'HEADER.HISTORY_INFO' where id = 5;")
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("update routes set path = 'task-history', name = 'HEADER.TASK_INFO' where id = 5;")
    # ### end Alembic commands ###
