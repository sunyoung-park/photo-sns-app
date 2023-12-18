from flask import request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from flask_restful import Resource
from mysql_connection import get_connection
from mysql.connector import Error

from email_validator import validate_email, EmailNotValidError
from utils import check_password, hash_password


class UserRegisterResource(Resource) :
    
    def post(self) :

        data = request.get_json()

        # Email Validation
        try :
            validate_email(data['email'])
        except EmailNotValidError as e :
            print(e)
            return{'error' : str(e)}, 400
        
        
        # Password Validation
        
        if len(data['password']) < 4 or len(data['password']) > 14 :
            return {'error':'비밀번호 길이가 올바르지 않습니다.'}, 400
        

        # Password Hashing
        password = hash_password(data['password'])

        print(password)


        # User table DB save

        try :
            connection= get_connection()
            
            query = '''insert into user
                        (email, password,nickname)
                        values
                        (%s,%s,%s);'''
            
            record = (data['email'],
                      password,                      
                      data['nickname'])
            
            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()


            # insert ID
            user_id = cursor.lastrowid

            cursor.close()
            connection.close() 

        except Error as e :
            print(e)
            cursor.close()
            connection.close() 
            return{'error':str(e)},500
        
        # user table id make JWT token

        access_token = create_access_token(user_id)

        return {'result':'sucess','access_token':access_token}, 200
    


class UserLoginResource(Resource) :

    def post(self) :

        data = request.get_json()

        try :
            connection = get_connection()
            query = '''select *
                        from user
                        where email = %s;'''
            record = (data['email'],)

            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, record)

            result_list = cursor.fetchall()

            print(result_list)

            cursor.close()
            connection.close()

        except Error as e :
            print(e)
            cursor.close()
            connection.close()
            return{"error":str(e)}, 500
        

        # 회원가입 시 정보가 없을 때
        if len(result_list) == 0 :
            return {'error':'회원가입을 하세요.'}, 400
        
        # email 있으면 password 확인

        print(data['password'])

        print(result_list[0]['password'])

        check = check_password(data['password'], result_list[0]['password']) 

        

        # 비밀번호 안 맞으면
        if check == False :
            return{'error':'비밀번호가 일치하지 않습니다.'}, 406 #not access
        
        # JWT 생성하여 클라이언트에게 전달
        access_token = create_access_token(result_list[0]['id'])

        return{'result':'success','accessToken':access_token}, 200
    
jwt_blocklist = set()


class UserLogoutResource(Resource) :

    @jwt_required()
    def delete(self) :

        jti = get_jwt()['jti']
        print(jti)

        jwt_blocklist.add(jti)

        return{'result':'success'}, 200


class FollowsResource(Resource) :

    @jwt_required()
    def post(self, followee_id) :

        user_id = get_jwt_identity()

        try :
            connection = get_connection()
            query = '''insert into follows
                    (followerId, followeeId)
                    values
                    (%s, %s);'''
            record = (user_id, followee_id)
            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()
            cursor.close()
            connection.close()

        except Error as e:
            print(e)
            return {'result':'fail', 'error':str(e)}, 500
        
        return {'result':'success'}
    
    @jwt_required()
    def delete(self, followee_id) :
        user_id = get_jwt_identity()

        try :
            connection = get_connection()
            query = '''delete from follows
                    where followerId = %s and followeeId = %s;'''
            record = (user_id, followee_id)
            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()
            cursor.close()
            connection.close()

        except Error as e:
            print(e)
            return {'result':'fail', 'error':str(e)}, 500
        
        return {'result':'success'}
     














