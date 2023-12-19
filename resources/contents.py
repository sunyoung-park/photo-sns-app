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
        # 넣어줘야 한다.(가장 중요 ★★★★★)

        try :
            connection = get_connection()

            # 1. content 테이블에 데이터를 넣어준다.


            query = '''insert into content
                        (userId, imgUrl, title, text)
                        values
                        (%s,%s,%s,%s);'''
            
            imgUrl = Config.S3_LOCATION + new_file_name            

            record = (userId, imgUrl, title, text)
        
            
            cursor = connection.cursor()
            cursor.execute(query, record)

            content_id = cursor.lastrowid # ★★

            # 2. tag_name 테이블에 처리를 해준다.
            #   리코그니션을 이용해서 받아온 label이,
            #   tag_name 테이블에 이미 존재하면,
            #   그 아이디만 가져오고,
            #   그렇지 않으면, 테이블에 인서트 한 후에
            #   그 아이디를 가져온다.

            for tag in tag_list :
                tag = tag.lower()
                query = '''select *
                            from tag_name
                            where name = %s;'''
                record = (tag, )
                cursor = connection.cursor(dictionary=True)
                cursor.execute(query, record)

                result_list = cursor.fetchall()

                # 태그가 이미 테이블에 있으면, 아이디만 가져오고
                if len(result_list) != 0 : # 또는 == 1
                    tag_name_id = result_list[0]['id']
                else :
                    # 태그가 테이블에 없으면, insert 한다.
                    query = '''insert into tag_name
                                (name)
                                values
                                (%s);'''
                    record = (tag, )
                    cursor = connection.cursor(dictionary=True)
                    cursor.execute(query, record)

                    tag_name_id = cursor.lastrowid    


            # 3. 위의 태그 네임 아이디와, 포스팅 아이디를
            # 이용해서, tag 테이블에 데이터를 넣어준다.
                    
                query = '''insert into tag
                            (contentId,tagNameId)
                            values
                            (%s,%s);'''           

                record = (content_id, tag_name_id)        
                
                cursor = connection.cursor()
                cursor.execute(query, record)

            # 트랜잭션 처리를 위해서
            # 커밋은 테이블 처리를 다 하고나서
            # 마지막에 한번 해준다.
            # 이렇게 해주면, 중간에 다른 테이블에서
            # 문제가 발생하면, 모든 테이블이 원상복구(롤백)된다.

            # 이 기능을 트랜잭션이라고 한다.(중요 ★★★★★)
            connection.commit() # 위에서의 작업이 전부 성공하면 반영하라 (트랜잭션 처리)

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
            if label['Confidence'] >= 90 :
                label_list.append(label['Name'])

        return label_list

    @jwt_required()
    def get(self) :
        offset = request.args.get('offset')
        limit = request.args.get('limit')

        user_id = get_jwt_identity()

        try :
            connection = get_connection()
            query = '''select c.id contentId, c.imgUrl, c.title, c.text, u.email, count(f.id) cntLike, if(f2.userId is null,0,1) isLike, c.createdAt
                        from follows ff
                        join content c
                        on ff.followeeId = c.userId
                        join user u
                        on c.userId = u.id
                        left join favorite f
                        on f.contentId=c.id
                        left join favorite f2
                        on c.id = f2.contentId and f2.userId = %s
                        where ff.followerId = %s
                        group by c.id
                        order by c.createdAt desc
                        limit '''+ offset +''','''+ limit +''';'''

            record = (user_id, user_id)

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


class PhotoResource(Resource) :

    @jwt_required(optional=True)
    def get(self, post_id) :
        user_id = get_jwt_identity()

        try :
            connection = get_connection()

            query = '''select c.id as postId, c.imgUrl, c.title, c.text,
                        u.id,u.email,c.createdAt,
                        count(f.id) as likeCnt,
                        if(f2.id is null,0,1) as isLike
                        from content c
                        join user u
                        on c.userId = u.id
                        left join favorite f
                        on c.id = f.contentId
                        left join favorite f2
                        on c.id = f2.contentId and f2.userId = %s
                        where c.id = %s;'''
            
            
            record = (user_id, post_id)

            cursor = connection.cursor(dictionary=True)

            cursor.execute(query, record)

            result_list = cursor.fetchall() # 가져온 것을 끄집어 내는 것

            if len(result_list) == 0 :
                return {'error':'데이터 없음'}, 400

            print(result_list)            

            # todo : 데이터 변수 작업 ## todo 리스트 표시...?
            post = result_list[0]



            query ='''select concat('#',tn.name) tag
                    from tag t
                    join tag_name tn
                    on t.tagNameId = tn.id
                    where t.contentId= %s;'''
            
            record = (post_id,)
            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, record)
            result_list = cursor.fetchall()
            
            print(result_list)

            tag = []
            for tag_dict in result_list :
                tag.append(tag_dict['tag'])

            cursor.close()
            connection.close()


        except Error as e:
            print(e)
            cursor.close()
            connection.close()
            return{"result":"fail", "error":str(e)}, 500

        print()
        print(post)
        print()
        print(tag)

        
            
           

        post['createdAt']= post['createdAt'].isoformat()

    

        return{'result':'success',
               'post': post,
               'tag':tag}



    
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
    

