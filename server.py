#! /usr/bin/python
# -*- coding: utf-8  -*-
import random
import string
import json
from collections import defaultdict


from tornado import ioloop
from tornado.websocket import WebSocketHandler
from tornado.web import Application
from tornado.web import RequestHandler


from constants import ALLOWED_COMMANDS
from constants import CMD_CREATEROOM, CMD_GETROOMLIST, CMD_GETUSERLIST
from constants import CMD_CHANGENICK, CMD_JOINROOM, CMD_LEAVEROOM, CMD_MESSAGE

RANDOM_USERNAME_LENGTH = 10


def generate_random_username():
    return "".join(random.choice(string.letters) for i in range(RANDOM_USERNAME_LENGTH))


class UserAlreadyExistsError(Exception):
    pass


class Room(object):
    def __init__(self, user_handlers, name, users=None):
        if users is None:
            self.users = set()
        self.users = users
        self.name = name
        self.user_handlers = user_handlers

    @property
    def users(self):
        return self.users

    @property
    def name(self):
        return self.name

    def broadcast(self, msg):
        for user in users:
            try:
                handler = self.user_handlers[user]
            except KeyError:
                pass
            else:
                handler.write_message(msg)

    def join(self, username):
        if username in users:
            raise UserAlreadyExistsError
        self.users.add(username)
        self.broadcast({"event": "joinroom",
                        "username": username,
                        "room": self.name})

    def leave(self, username):
        if username not in users:
            return
        self.users.remove(username)
        self.broadcast({"event": "leaveroom",
                        "username": username,
                        "room": self.name})

    def message(self, username, message):
        if username not in users:
            return
        self.broadcast({"event": "message",
                        "username": username,
                        "message": message})


class WebSocketChat(WebSocketHandler):
    def initialize(self, users, rooms, users2rooms):
        self.users = users
        self.rooms = rooms
        self.users2rooms = users2rooms

    def check_origin(self, origin):
        return True

    def open(self):
        self.username = generate_random_username()
        self.users[self.username] = self

    def write_error(self, error_msg):
        self.write_message({"error": error_msg})

    def on_message(self, message):
        try:
            msg = json.loads(message)
        except ValueError:
            return
        if ("cmd" not in msg) or ("args" not in msg):
            return
        cmd = msg["cmd"]
        if cmd not in ALLOWED_COMMANDS:
            self.write_error("Incorrect command")
        if cmd == CMD_CREATEROOM:
            room_name = msg["args"]["room_name"]
            if room_name in self.rooms:
                self.write_error("Room already exists")
            else:
                self.rooms[room_name] = Room(self.users, room_name)
                msg = {"event": "roomcreated", "name": room_name}
                self.broadcast_all(msg)
        elif cmd == CMD_GETROOMLIST:
            msg = {"event": "roomlist", "rooms": list(self.rooms)}
            self.write_message(msg)
        elif cmd == CMD_GETUSERLIST:
            msg = {"event": "userlist", "users": list(self.users)}
            self.write_message(msg)
        elif cmd == CMD_CHANGENICK:
            to_nick = cmd["args"]["change_to"]
            if to_nick in self.users:
                self.write_error("This nick already used")
            else:
                msg = {"event": "changed_nick",
                       "from": self.username,
                       "to": to_nick}
                self.broadcast_all(msg)
        elif cmd == CMD_JOINROOM or cmd == CMD_LEAVEROOM:
            room_name = cmd["args"]["name"]
            if room_name not in self.rooms:
                self.write_error("Operation with nonexistent room")
            else:
                if cmd == CMD_JOINROOM:
                    self.rooms[room_name].join(self.username)
                    self.users2rooms[self.username].add(room_name)
                else:
                    self.rooms[room_name].leave(self.username)
                    self.users2rooms[self.username].remove(room_name)
        elif cmd == CMD_MESSAGE:
            msg = cmd["args"]["msg"]
            for room_name in self.users2rooms[self.username]:
                self.rooms[room_name].message(self.username, msg)

    def broadcast_all(self, msg):
        for handler in self.users.values():
            handler.write_message(msg)

    def on_close(self):
        for room in self.rooms:
            room.leave(self.username)
        del self.users[self.username]


class IndexPage(RequestHandler):
    def get(self):
        self.render("templates/client.html")


if __name__ == '__main__':
    users = {}
    rooms = {}
    users2rooms = defaultdict(set)
    application = Application([
        (r'/websocket', WebSocketChat, dict(users=users, rooms=rooms, users2rooms=users2rooms)),
        (r'/', IndexPage)
    ])
    application.listen(8888)
    ioloop.IOLoop.instance().start()
