from setuptools import find_packages, setup
import os

package_name = 'store_node'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name, ['store_node/T_gripper2camera.npy']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='junhyeok',
    maintainer_email='liebeujs@gmamil.com',
    description='TODO: Package description',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'main_manager = store_node.main_manager:main',
            'robot_control = store_node.robot_control:main',
            'database_manager = store_node.database_manager:main',
            'db_ai_analytics_manager = store_node.db_ai_analytics_manager:main',
            'admin_auth_manager = store_node.admin_auth_manager:main',
            'api_server = store_node.main:main',
            'counter_qr_node = store_node.counter_qr_node:main',
            'gripper_vision_node = store_node.gripper_vision_node:main',
        ],
    },
)
