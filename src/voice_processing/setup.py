from setuptools import find_packages, setup
import os

package_name = 'voice_processing'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('lib', package_name), [os.path.join(package_name, '.env')]),
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
            'voice_manager = voice_processing.voice_manager:main',
        ],
    },
)
