#! /usr/bin/python
# -*- coding: utf-8  -*-
import random
import string


from tornado import ioloop
from tornado.websocket import WebSocketHandler
from tornado.web import Application


def generate_random_username():
    return "".join(random.choice(string.letters) for i in range(8))


class UserAlreadyExistsError(Exception):
    pass


class Room(object):
    def __init__(self, user_handlers, users=None):
        if users is None:
            self.users = set()
        self.users = users
        self.user_handlers = user_handlers

    @property
    def users(self):
        return self.users

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
        self.broadcast(username + " has joined the room")

    def leave(self, username):
        if username not in users:
            return
        self.users.remove(username)
        self.broadcast(username + " left the room")


class EchoWebSocket(WebSocketHandler):
    def initialize(self, users, rooms):
        self.users = users
        self.rooms = rooms

    def check_origin(self, origin):
        return True

    def open(self):
        self.username = generate_random_username()
        self.users[self.username] = self

    def on_message(self, message):
        self.write_message("You said:" + message)

    def on_close(self):
        for room in self.rooms:
            room.leave(self.username)
        del self.users[self.username]


if __name__ == '__main__':
    users = {}
    rooms = {}
    application = Application([
        (r'/websocket', EchoWebSocket, dict(users=users, rooms=rooms))
    ])
    application.listen(8888)
    ioloop.IOLoop.instance().start()
