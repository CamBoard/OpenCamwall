import json
import logging
import time
from pathlib import Path
from mirai import Image

import config
import pkg.chat.manager
import pkg.database.database
import pkg.database.mediamgr

import pkg.routines.qzone_routines
import pkg.qzone.model
import pkg.qzone.publisher
import pkg.audit.recorder.likers

import pkg.funcmgr.control as funcmgr


@funcmgr.function([funcmgr.Functions.ROUTINE_POST_SEND_TO_ADMINS])
def new_post_incoming(post_data):
    # 下载图片并准备消息链
    medias = json.loads(post_data['media'])
    message_chain = [
        "[bot]" +
        "收到新投稿\n" +
        "内容:\n" +
        post_data['text'] + "\n"
                            "图片:" + str(len(medias)) + "张\n" +
        "匿名:" + ("是" if post_data['anonymous'] else "否") + "\n" +
        "QQ:" + str(post_data['qq']) + "\n" +
        "id:##" + str(post_data['id'])
    ]
    if len(medias) > 0:
        # 下载所有图片
        publisher = pkg.qzone.publisher.get_inst()
        for media in medias:
            if media.startswith('cloud:'):
                message_chain.append(Image(path=publisher
                                           .download_cloud_image(media, 'cache/{}'.format(int(time.time())))))
            else:
                message_chain.append(Image(path=pkg.database.mediamgr.get_inst().get_file_path(media)))

    chat_inst = pkg.chat.manager.get_inst()
    if chat_inst is not None:
        chat_inst.send_message_to_admin_groups(message_chain)


def post_status_changed(post_id, new_status):
    chat_inst = pkg.chat.manager.get_inst()
    if new_status == '取消':
        if chat_inst is not None:
            chat_inst.send_message_to_admin_groups([
                "[bot]" + "投稿已取消" + "\n" +
                "id:##" + str(post_id)
            ])
    elif new_status == '拒绝':
        db_inst = pkg.database.database.get_inst()
        post = db_inst.pull_one_post(post_id=post_id)
        if post['review'] != '无原因':
            if chat_inst is not None:
                chat_inst.send_message(target_type='person', target=post['qq'], message="[bot](无需回复)\n您{}的投稿已被拒绝\n"
                                                                                        "id:##{}\n内容:{}\n图片:{}张\n原因:{}"
                                       .format('匿名' if post['anonymous'] else '不匿名', post_id, post['text'],
                                               str(len(json.loads(post['media']))), post['review']))
    elif new_status == '通过':
        pkg.routines.qzone_routines.clean_pending_posts()

    elif new_status == '撤回':
        msg_chain = []
        try:
            # 查找此稿件的tid
            db_inst = pkg.database.database.get_inst()

            result = db_inst.get_published_tid(post_id)

            if result['result'] != 'success':
                raise Exception(result['result'])

            tid = result['tid']

            qzone_inst = pkg.qzone.model.get_inst()
            qzone_inst.emotion_set_private(tid=tid)

            msg_chain.append("[bot]已撤回##{}".format(post_id))
        except Exception as e:
            msg_chain.append("[bot]撤回失败\n" + str(e))

        if chat_inst is not None:
            chat_inst.send_message_to_admin_groups(msg_chain)


@funcmgr.function([funcmgr.Functions.ROUTINE_POST_POST_FINISHED])
def post_finished(post_id, qq, tid):
    # 验证是否发表成功
    tid_valid = False
    for i in range(4):
        tid_valid = pkg.qzone.model.get_inst().tid_valid(tid)
        if tid_valid:
            break
        time.sleep(3)

    if tid_valid:
        # 把tid写入数据库
        pkg.audit.recorder.likers.go(target=pkg.audit.recorder.likers.fetch_new_emotions)

        # 发送赞助信息给用户
        if config.sponsor_message != '':
            # 包装消息链
            message_chain = [config.sponsor_message]

            for sponsor_qrcode in config.sponsor_qrcode_path:
                if Path(sponsor_qrcode).exists():
                    message_chain.append(Image(path=sponsor_qrcode))

            chat_inst = pkg.chat.manager.get_inst()

            if chat_inst is not None:
                chat_inst.send_message("person", qq, message_chain)
            logging.info("发送赞助信息给用户:{}".format(qq))
