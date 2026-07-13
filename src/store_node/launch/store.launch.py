import os
from launch import LaunchDescription
from launch.actions import ExecuteProcess, LogInfo
from launch_ros.actions import Node

def generate_launch_description():

    return LaunchDescription([
        
        Node(
            package='store_node',       
            executable='main_manager', 
            name='main_manager',
            output='screen'
        ),

        Node(
            package='store_node',       
            executable='robot_control', 
            name='robot_control',
            output='screen'
        ),

        Node(
            package='store_node',       
            executable='gripper_vision_node', 
            name='vision',
            output='screen'
        ),

        Node(
            package='store_node',       
            executable='counter_qr_node', 
            name='QR',
            output='screen'
        ),

        Node(
            package='voice_processing',       
            executable='voice_manager', 
            name='voice_manager',
            output='screen'
        ),

        Node(
            package='store_node',       
            executable='admin_auth_manager', 
            name='Admin',
            output='screen'
        ),

        Node(
            package='store_node',       
            executable='database_manager', 
            name='DB',
            output='screen'
        ),
        
        Node(
            package='store_node',       
            executable='api_manager', 
            name='API',
            output='screen'
        ),
    ])