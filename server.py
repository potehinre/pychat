""" pychat - WebSocket Chat With Rooms """
#! /usr/bin/python
# -*- coding: utf-8  -*-
import json
import argparse
import logging
from uuid import uuid4


from tornado import ioloop
from tornado.websocket import WebSocketHandler
from tornado.websocket import WebSocketClosedError
from tornado.web import Application
from tornado.web import RequestHandler


from constants import ALLOWED_COMMANDS
from constants import CMD_CREATEROOM, CMD_GETROOMLIST, CMD_GETUSERLIST
from constants import CMD_CHANGENICK, CMD_JOINROOM, CMD_LEAVEROOM
from constants import CMD_MESSAGE, CMD_LOGIN
from constants import EVT_ROOMLIST, EVT_USERLIST, EVT_CHANGEDNICK
from constants import EVT_JOINROOM, EVT_LEAVEROOM, EVT_MESSAGE
from constants import EVT_LOGIN, EVT_ROOMCREATED


class Room(object):
    def __init__(self, user_handlers, name, users=None):
        if users is None:
            self.users = set()
        else:
            self.users = users
        self.name = name
        self.user_handlers = user_handlers

    def change_nick(self, from_nick, to_nick):
        self.users.discard(from_nick)
        self.users.add(to_nick)

    def broadcast(self, msg):
        for user in self.users:
            try:
                handler = self.user_handlers[user]
            except KeyError:
                logging.warning("user %s exists in a room but had no handler", user)
            else:
                try:
                    handler.write_message(msg)
                except WebSocketClosedError as e:
                    logging.error("Unexpected socket close during room broadcast: %s", e)

    def join(self, username):
        if username in self.users:
            return
        self.users.add(username)
        self.broadcast({"event": EVT_JOINROOM,
                        "username": username,
                        "room": self.name})

    def leave(self, username):
        if username not in self.users:
            return
        self.broadcast({"event": EVT_LEAVEROOM,
                        "username": username,
                        "room": self.name})
        self.users.discard(username)

    def message(self, username, message):
        if username not in self.users:
            return
        self.broadcast({"event": EVT_MESSAGE,
                        "username": username,
                        "message": message})


class WebSocketChat(WebSocketHandler):
    def initialize(self, users, rooms, user2room, loggedin_users):
        self.users = users
        self.rooms = rooms
        self.user2room = user2room
        self.loggedin_users = loggedin_users

    def check_origin(self, origin):
        return True

    def open(self):
        self.username = str(uuid4())
        self.users[self.username] = self

    def write_error(self, error_msg):
        try:
            self.write_message({"error": error_msg})
        except WebSocketClosedError as e:
            logging.error("Unexpected socket close during write_error: %s", e)

    def broadcast_roomlist(self):
        msg = {"event": EVT_ROOMLIST, "rooms": list(self.rooms)}
        self.broadcast_all(msg)

    def broadcast_userlist(self):
        msg = {"event": EVT_USERLIST, "users": list(self.loggedin_users)}
        self.broadcast_all(msg)

    def on_message(self, message):
        try:
            msg = json.loads(message)
        except ValueError:
            logging.error("Client sent incorrect json: %s", message)
            return
        if ("cmd" not in msg):
            self.write_error("Incorrect command")
            logging.error("Client sent incorrect command: %s", msg)
            return
        cmd = msg["cmd"]
        if cmd not in ALLOWED_COMMANDS:
            self.write_error("Incorrect command")
            return
        if cmd not in (CMD_LOGIN, CMD_GETROOMLIST, CMD_GETUSERLIST) \
                and self.username not in self.loggedin_users:
            self.write_error("You must be logged in before execute commands")
            return
        if cmd == CMD_LOGIN:
            try:
                nick = msg["args"]["nick"]
            except KeyError:
                logging.error("Client sent incorrect login command: %s", msg)
                return
            if self.username in self.loggedin_users:
                self.write_error("You had already logged in")
                logging.info("Client %s tried to login more than one time", self.username)
                return
            if nick in self.users:
                self.write_error("This nick already used")
                return
            else:
                del self.users[self.username]
                self.username = nick
                self.loggedin_users.add(self.username)
                self.users[self.username] = self
                self.broadcast_all({"event": EVT_LOGIN, "nick": nick})
                self.broadcast_userlist()
        elif cmd == CMD_CREATEROOM:
            try:
                room_name = msg["args"]["room_name"]
            except KeyError:
                logging.error("Client sent incorrect %s command: %s", cmd, msg)
                return
            if room_name in self.rooms:
                self.write_error("Room already exists")
            else:
                self.rooms[room_name] = Room(self.users, room_name)
                msg = {"event": EVT_ROOMCREATED, "name": room_name}
                self.broadcast_all(msg)
                self.broadcast_roomlist()
        elif cmd == CMD_GETROOMLIST:
            msg = {"event": EVT_ROOMLIST, "rooms": list(self.rooms)}
            self.write_message(msg)
        elif cmd == CMD_GETUSERLIST:
            msg = {"event": EVT_USERLIST, "users": list(self.loggedin_users)}
            self.write_message(msg)
        elif cmd == CMD_CHANGENICK:
            try:
                to_nick = msg["args"]["change_to"]
            except KeyError:
                logging.error("Client sent incorrect %s command: %s", cmd, msg)
                return
            if to_nick in self.users:
                self.write_error("This nick already used")
            else:
                from_nick = self.username
                self.loggedin_users.discard(from_nick)
                self.loggedin_users.add(to_nick)
                self.users[to_nick] = self.users[self.username]
                if self.username in self.user2room:
                    current_room = self.user2room[self.username]
                    self.user2room[to_nick] = self.user2room[self.username]
                    self.rooms[current_room].change_nick(from_nick, to_nick)
                    del self.user2room[self.username]
                del self.users[self.username]
                self.username = to_nick
                msg = {"event": EVT_CHANGEDNICK,
                       "from": from_nick,
                       "to": to_nick}
                self.broadcast_all(msg)
                self.broadcast_userlist()
        elif cmd == CMD_LEAVEROOM:
            if self.username in self.user2room:
                current_room = self.user2room[self.username]
                self.rooms[current_room].leave(self.username)
                del self.user2room[self.username]
        elif cmd == CMD_JOINROOM:
            try:
                room_name = msg["args"]["name"]
            except KeyError:
                logging.error("Client sent incorrect %s command: %s", cmd, msg)
                return
            if room_name not in self.rooms:
                self.write_error("Cannot join unexistent room")
            else:
                if self.username in self.user2room:
                    current_room = self.user2room[self.username]
                    self.rooms[current_room].leave(self.username)
                self.rooms[room_name].join(self.username)
                self.user2room[self.username] = room_name
        elif cmd == CMD_MESSAGE:
            msg = msg["args"]["msg"]
            if self.username in self.user2room:
                current_room = self.user2room[self.username]
                self.rooms[current_room].message(self.username, msg)

    def broadcast_all(self, msg):
        for handler in self.users.values():
            try:
                handler.write_message(msg)
            except WebSocketClosedError as e:
                logging.error("Unexpected socket close during broadcasting message to all: %s", e)

    def on_close(self):
        del self.users[self.username]
        self.loggedin_users.discard(self.username)
        self.broadcast_userlist()


class IndexPage(RequestHandler):
    def get(self):
        self.render("templates/client.html")


if __name__ == '__main__':
    argparse = argparse.ArgumentParser(__doc__)
    argparse.add_argument("-p", "--port", type=int, action="store", dest="port",
                          default=8888, help="on which port run wsServer")
    argparse.add_argument("--loglevel", type=str, action="store", dest="loglevel",
                          default=logging.DEBUG)
    args = argparse.parse_args()
    logging.basicConfig(format=u'%(levelname)-8s [%(asctime)s] %(message)s', level=args.loglevel)
    users = {}
    rooms = {}
    user2room = {}
    loggedin_users = set()
    application = Application([
        (r'/websocket', WebSocketChat,
                        dict(users=users,
                             rooms=rooms,
                             user2room=user2room,
                             loggedin_users=loggedin_users)),
        (r'/', IndexPage)
    ])
    application.listen(args.port)
    ioloop.IOLoop.instance().start()
