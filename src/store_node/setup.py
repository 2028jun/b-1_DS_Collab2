from setuptools import find_packages, setup

package_name = 'store_node'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
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
            'main_manager = store_nodes.main_manager:main',
            'robot_control = store_nodes.robot_control:main',
            'vision_detector = store_nodes.vision_detector:main',
            'voice_auth = store_nodes.voice_auth:main',
            'database_manager = store_nodes.database_manager:main',
        ],
    },
)
