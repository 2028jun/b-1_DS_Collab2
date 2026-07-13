설치 필요
sudo pip3 install ultralytics

numpy 버전 1.xx로 실행 필요
기존 버전이 2.xx 일 시 실행
pip3 uninstall numpy -y
pip3 install "numpy<2"

opencv 버전과 충돌날 수 있음 충돌 확인 시 실행
python3 -m pip install --user --force-reinstall "numpy==1.26.4" "opencv-python==4.10.0.84"

package.xml 내용 추가
  <depend>python3-ultralytics</depend> 

setup.py 내용 변경
    install_requires=['setuptools',
                      'ultralytics'],

GetSalesAnalytics.srv 추가
db_ai_analytics_manager.py 추가
voice_manager.py 내용 추가
setup.py 내용 추가
'db_ai_analytics_manager = store_node.db_ai_analytics_manager:main',
