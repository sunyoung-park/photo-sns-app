from datetime import datetime
from flask import request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from flask_restful import Resource
from config import Config
from mysql_connection import get_connection
from mysql.connector import Error

import boto3 


class PhotoListResource(Resource) :

    @jwt_required()
    def post(self):

        file = request.files.get('photo')
        title = request.form.get('title')
        text = request.form.get('text')        

        userId = get_jwt_identity()

        if file is None :
            return {'error' : '파일을 업로드 하세요.'}, 400  # 클라이언트가 잘못 줌.
        
        
        # 파일명을 회사의 파일명 정책에 맞게 변경한다.
        # 파일명은 유니크해야 한다.

        current_time = datetime.now()

        new_file_name = current_time.isoformat().replace(':','_')+ str(userId) + '.jpg'

        # 유저가 올린 파일의 이름을,
        # 새로운 파일 이름으로 변경한다.

        file.filename = new_file_name   # file. 클래스의 멤버변수에 저장해라

        # S3에 업로드 하면 된다.

        s3 = boto3.client('s3',
                     aws_access_key_id = Config.AWS_ACCESS_KEY_ID,
                     aws_secret_access_key = Config.AWS_SECRET_ACCESS_KEY)
        
        
        try :
            s3.upload_fileobj(file, 
                              Config.S3_BUCKET, 
                              file.filename,
                              ExtraArgs = {'ACL' : 'public-read',
                                           'ContentType' : 'image/jpeg'})

        
        except Error as e :
            print(e)
            return{'error':str(e)}, 500

        # rekogintion 서비스를 이용해서
        # object detection 하여, 태그 이름을 가져온다.

        tag_list = self.detect_labels(new_file_name, Config.S3_BUCKET)

        print(tag_list)
                
        # DB의 posting 테이블에 데이터를 넣어야 하고,
        # tag_name 테이블과 tag 테이블에도 데이터를
        # 넣어줘야 한다.

        try :
            connection = get_connection()

            query = '''insert into content
                        (userId, imgUrl, title, text)
                        values
                        (%s,%s,%s,%s);
                        
                        insert into tag
                        (contentId,userId)
                        values
                        (%s,%s);

                        insert into tag_name
                        (name)
                        values
                        (%s);'''
            
            imgUrl = Config.S3_LOCATION + new_file_name            

            record = (userId, imgUrl, title, text,)
            
            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()

            cursor.close()
            connection.close()



        except Error as e:
            print(e)
            cursor.close()
            connection.close()
            return{'result':'fail','error':str(e)}, 500

        return{'result':'success',
                'imgUrl':imgUrl,
                'text' : text}, 200
    
    @jwt_required()
    def get(self) :

        order = request.args.get('order')
        offset = request.args.get('offset')
        limit = request.args.get('limit')

        user_id = get_jwt_identity()

        try :
            connection = get_connection()
            query = '''select c.id, c.imgUrl, c.title, c.text, c.createdAt , count(f.id) cntLike, if(f.userId=%s,1,0) isLike
                    from content c
                    join user u
                    on c.userId = u.id
                    left join favorite f
                    on f.contentId =c.id
                    group by c.id
                    order by '''+ order +''' desc
                    limit '''+ offset +''','''+ limit +''';'''

            record = (user_id,)

            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, record)

            result_list = cursor.fetchall()

            cursor.close()
            connection.close()


        except Error as e :
            print(e)
            cursor.close()
            connection.close()
            return{'error':str(e)}, 500
        
        print(result_list)

        i = 0
        for row in result_list :
            result_list[i]['createdAt']= row['createdAt'].isoformat()
            i = i + 1
        
        return{'result':'success',
               'items':result_list,
               'count':len(result_list)}

    def detect_labels(self, photo, bucket):


        # session = boto3.Session(profile_name='serverless_user')
        # client = session.client('rekognition')

        # 클라이언트 연결

        client = boto3.client('rekognition',
                              'ap-northeast-2',
                              aws_access_key_id = Config.AWS_ACCESS_KEY_ID,
                              aws_secret_access_key = Config.AWS_SECRET_ACCESS_KEY)

        #detect_lable 해주라

        response = client.detect_labels(Image={'S3Object':{'Bucket':bucket,'Name':photo}},
        MaxLabels=5, # MaxLabels=10 라벨 수 제한하기
        # Uncomment to use image properties and filtration settings
        #Features=["GENERAL_LABELS", "IMAGE_PROPERTIES"],
        #Settings={"GeneralLabels": {"LabelInclusionFilters":["Cat"]},
        # "ImageProperties": {"MaxDominantColors":10}}
        )

        print('Detected labels for ' + photo)
        print()

        # 함수 수정(231215 12:40)

        label_list = []
        for label in response['Labels']:
            print("label: " + label['Name'])
            print("Confidence: " + str(label['Confidence']))
            if label['Confidence'] >= 90 :
                label_list.append(label['Name'])                
                label_list.append(label['Confidence'])

        return label_list




class PhotoResource(Resource) :

    
    @jwt_required()
    def delete(self, post_id) :

        userId = get_jwt_identity()

        try : 
            
            connection = get_connection()

            query = '''delete from content
                        where id = %s and userId = %s;'''
            
            record = (post_id, userId)

            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()

            cursor.close()
            connection.close()

        except Error as e :
            print(e)
            cursor.close()
            connection.close()
            return {"result":"fail","error":str(e)}, 500

        return {"result":"success"}, 200
    
    @jwt_required()
    def put(self, post_id) :              

        file = request.files.get('photo')
        title = request.form.get('title')
        text = request.form.get('text')    

        userId = get_jwt_identity()

        if file is None :
            return {'error' : '파일을 업로드 하세요.'}, 400  # 클라이언트가 잘못 줌.
        
        
        # 파일명을 회사의 파일명 정책에 맞게 변경한다.
        # 파일명은 유니크해야 한다.

        current_time = datetime.now()

        new_file_name = current_time.isoformat().replace(':','_')+ str(userId) + '.jpg'

        # 유저가 올린 파일의 이름을,
        # 새로운 파일 이름으로 변경한다.

        file.filename = new_file_name   # file. 클래스의 멤버변수에 저장해라

        # S3에 업로드 하면 된다.

        s3 = boto3.client('s3',
                     aws_access_key_id = Config.AWS_ACCESS_KEY_ID,
                     aws_secret_access_key = Config.AWS_SECRET_ACCESS_KEY)
        
        
        try :
            s3.upload_fileobj(file, 
                              Config.S3_BUCKET, 
                              file.filename,
                              ExtraArgs = {'ACL' : 'public-read',
                                           'ContentType' : 'image/jpeg'})

        
        except Error as e :
            print(e)
            return{'error':str(e)}, 500

        try :
            
            connection = get_connection()

            query = '''update content
                        set imgUrl=%s, title =%s, text =%s
                        where id = %s and userId = %s;'''
            record =(new_file_name, title, text,post_id, userId)
            
            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()

            cursor.close()
            connection.close()
            

        except Error as e :
            print(e)
            cursor.close()
            connection.close()
            return{"result":"fail","error":str(e)}, 500
        return {"result":"success"}, 200
    

class LikeResource(Resource) :

    @jwt_required()
    def post(self, content_id) :

        user_id = get_jwt_identity()

        try :
            connection = get_connection()
            query = '''insert into favorite
                    (userId,contentId)
                    values
                    (%s, %s);'''
            record = (user_id, content_id)
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
    def delete(self, content_id) :
        user_id = get_jwt_identity()

        try :
            connection = get_connection()
            query = '''delete from favorite
                        where userId = %s and contentId = %s;'''
            record = (user_id, content_id)
            cursor = connection.cursor()
            cursor.execute(query, record)
            connection.commit()
            cursor.close()
            connection.close()

        except Error as e:
            print(e)
            return {'result':'fail', 'error':str(e)}, 500
        
        return {'result':'success'}
    

