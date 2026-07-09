import pymysql
import pymysql.cursors

conn = pymysql.connect(
    host='localhost',       # MySQL 서버 주소 (로컬인 경우 'localhost')
    # port=3306,          # 다른 포트번호 사용 시 설정
    user='root',            # MySQL 사용자명
    password='1234',        # MySQL 비밀번호
    database='exampledb',   # 사용할 데이터베이스 명
    charset='utf8mb4',      # UTF-8의 확장 버전

    # cursors 모듈: 쿼리를 실행할 새 커서를 만듬
    # DictCursor 클래스: DB의 sql 구문 실행 후, 조회된 결과를 딕셔너리 형태로 반환
    cursorclass=pymysql.cursors.DictCursor
)

cursor = conn.cursor()
cursor.execute("SELECT DATABASE()")

# cursor.fetchone() : 한번 호출에 하나의 row만 가져올 때 사용
# cursor.fetchall() 
# cursor.fetchmany(n)
print(f"현재 데이터베이스: {cursor.fetchone()}")
conn.close()