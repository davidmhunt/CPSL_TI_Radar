from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument,GroupAction,OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory

import os

ARGUMENTS = [
    DeclareLaunchArgument(
        'config_file',
        default_value='radar_0_IWR1843_SAR_2ms_fmt2.json',
        description='Bare filename from share/ti_radar_connect/config/system/'
    ),
    DeclareLaunchArgument(
        'radar_name', default_value='Radar_0',
        description='radar frame_id'),
    DeclareLaunchArgument(
        'stamp_delay_sec', default_value='0.00',
        description='delay to applied to the published radar messages time'),
    DeclareLaunchArgument(
        'publish_chirp_meta', default_value='false',
        description='publish SAR per-chirp metadata on <radar_name>/adc_meta (needs a dataFmt 2 config)'),
    DeclareLaunchArgument(
        'tf_prefix', default_value='',
        description='tf_prefix to apply to frame id')
]

def launch_setup(context,*args,**kwargs):
    radar_name = LaunchConfiguration('radar_name')
    config_file = LaunchConfiguration('config_file')
    stamp_delay_sec = LaunchConfiguration('stamp_delay_sec')
    tf_prefix = LaunchConfiguration('tf_prefix')
    publish_chirp_meta = LaunchConfiguration('publish_chirp_meta')

    #derive the full config path
    config_file_str = config_file.perform(context)
    package_share_dir = get_package_share_directory('ti_radar_connect')
    full_config_path = os.path.join(package_share_dir, "config", "system", config_file_str)

    #load the tf prefix
    tf_prefix_str = tf_prefix.perform(context)
    radar_name_str = radar_name.perform(context)
    # if (tf_prefix_str):
    #     frame_id_str = "{}/{}".format(tf_prefix_str,frame_id_str)

    nodes = GroupAction([
        Node(
            package='ti_radar_connect',
            executable='ti_radar_connect',
            name='ti_radar_connect_{}'.format(radar_name_str),
            output='screen',
            parameters=[{'config_path': full_config_path,
                         'radar_name':radar_name_str,
                         'tf_prefix':tf_prefix_str,
                         'stamp_delay_sec':stamp_delay_sec,
                         'publish_chirp_meta':ParameterValue(publish_chirp_meta, value_type=bool)}]
        )
    ])

    return [nodes]

def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld
