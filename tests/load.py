#!/usr/bin/env python
# flake8: noqa: E402

'''
WebSocket server-side load test program. Sends and receives traffic
that has a random payload (length and content) that is checksummed and
given a sequence number. Any errors are reported and counted.
'''

import logging
import optparse
import os
import random
import select
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from websockify.websockifyserver import WebSockifyRequestHandler
from websockify.websockifyserver import WebSockifyServer


class WebSocketLoadServer(WebSockifyServer):

    recv_cnt = 0
    send_cnt = 0

    def __init__(self, *args, **kwargs):
        self.delay = kwargs.pop('delay')

        WebSockifyServer.__init__(self, *args, **kwargs)


class WebSocketLoad(WebSockifyRequestHandler):

    max_packet_size = 10000

    def new_websocket_client(self):
        print("Prepopulating random array")
        self.rand_array = []
        for i in range(0, self.max_packet_size):
            self.rand_array.append(random.randint(0, 9))

        self.errors = 0
        self.send_cnt = 0
        self.recv_cnt = 0

        self.responder(self.request)

        print("accumulated errors:", self.errors)
        self.errors = 0

    def responder(self, client):
        c_pend = 0
        socks = [client]
        last_send = time.time() * 1000

        while True:
            ins, outs, excepts = select.select(socks, socks, socks, 1)
            if excepts:
                raise Exception("Socket exception")

            if client in ins:
                frames, closed = self.recv_frames()

                err = self.check(frames)
                if err:
                    self.errors = self.errors + 1
                    print(err)

                if closed:
                    break

            now = time.time() * 1000
            if client in outs:
                if c_pend:
                    last_send = now
                    c_pend = self.send_frames()
                elif now > (last_send + self.server.delay):
                    last_send = now
                    c_pend = self.send_frames([self.generate()])

    def generate(self):
        length = random.randint(10, self.max_packet_size)
        numlist = self.rand_array[self.max_packet_size - length:]
        chksum = sum(numlist)
        nums = "".join([str(n) for n in numlist])
        data = "^%d:%d:%d:%s$" % (self.send_cnt, length, chksum, nums)
        self.send_cnt += 1

        return data

    def check(self, frames):

        err = ""
        for data in frames:
            if data.count('$') > 1:
                raise Exception("Multiple parts within single packet")
            if len(data) == 0:
                self.traffic("_")
                continue

            if data[0] != "^":
                err += "buf did not start with '^'\n"
                continue

            try:
                cnt, length, chksum, nums = data[1:-1].split(':')
                cnt = int(cnt)
                length = int(length)
                chksum = int(chksum)
            except ValueError:
                print("\n<BOF>" + repr(data) + "<EOF>")
                err += "Invalid data format\n"
                continue

            if self.recv_cnt != cnt:
                err += "Expected count %d but got %d\n" % (self.recv_cnt, cnt)
                self.recv_cnt = cnt + 1
                continue

            self.recv_cnt += 1

            if len(nums) != length:
                err += "Expected length %d but got %d\n" % (length, len(nums))
                continue

            inv = nums.translate(None, "0123456789")
            if inv:
                err += "Invalid characters found: %s\n" % inv
                continue

            real_chksum = 0
            for num in nums:
                real_chksum += int(num)

            if real_chksum != chksum:
                err += "Expected checksum %d but real chksum is %d\n" % (chksum, real_chksum)
        return err


if __name__ == '__main__':
    parser = optparse.OptionParser(usage="%prog [options] listen_port")
    parser.add_option("--verbose", "-v", action="store_true",
                      help="verbose messages and per frame traffic")
    parser.add_option("--cert", default="self.pem",
                      help="SSL certificate file")
    parser.add_option("--key", default=None,
                      help="SSL key file (if separate from cert)")
    parser.add_option("--ssl-only", action="store_true",
                      help="disallow non-encrypted connections")
    (opts, args) = parser.parse_args()

    try:
        if len(args) != 1:
            raise ValueError
        opts.listen_port = int(args[0])

        if len(args) not in [1, 2]:
            raise ValueError
        opts.listen_port = int(args[0])
        if len(args) == 2:
            opts.delay = int(args[1])
        else:
            opts.delay = 10
    except ValueError:
        parser.error("Invalid arguments")

    logging.basicConfig(level=logging.INFO)

    opts.web = "."
    server = WebSocketLoadServer(WebSocketLoad, **opts.__dict__)
    server.start_server()
