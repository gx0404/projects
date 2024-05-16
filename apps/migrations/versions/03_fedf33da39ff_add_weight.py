"""V1.2.0: dpt_map_box 新增 `normal_weight`, `real_weight` 字段

Revision ID: fedf33da39ff
Revises: a5509a75ac8e
Create Date: 2022-07-04 11:32:00.105084

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'fedf33da39ff'
down_revision = '838f4ce50379'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        'dpt_map_box',
        sa.Column(
            'normal_weight',
            sa.Numeric(precision=10, scale=2),
            nullable=True,
            comment='标准重量'
        )
    )
    op.add_column(
        'dpt_map_box',
        sa.Column(
            'real_weight',
            sa.Numeric(precision=10, scale=2),
            nullable=True,
            comment='实际重量'
        )
    )
    op.rename_table('dpt_map_box', 'dpt_register_box')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('dpt_register_box', 'real_weight')
    op.drop_column('dpt_register_box', 'normal_weight')
    op.rename_table('dpt_register_box', 'dpt_map_box')
    # ### end Alembic commands ###
