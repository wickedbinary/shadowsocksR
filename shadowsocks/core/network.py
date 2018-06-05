from shadowsocks.core import eventloop, tcprelay, udprelay, asyncdns, daemon
from shadowsocks.lib import shell, socks
import logging
import time
import threading
import os
import sys
import signal


class Network:
    def sigusr1_handler(self, signum, frame):
        pass

    def sigusr2_handler(self, signum, frame):
        pass


class ClientNetwork(Network):
    def __init__(self, config):
        # initialize dns_resolver, loop
        self.tcp_server = None
        self.udp_server = None
        self.dns_resolver = None
        self.loop = None
        self.config = None
        self.alarm_period = 20
        self.loop = eventloop.EventLoop()
        self.dns_resolver = asyncdns.DNSResolver()
        self.dns_resolver.add_to_loop(self.loop)
        if config is not None:
            self.init(config)

    def init(self, config):
        self.config = config
        self.tcp_server = tcprelay.TCPRelay(config, self.dns_resolver, True)
        self.udp_server = udprelay.UDPRelay(config, self.dns_resolver, True)
        self.tcp_server.add_to_loop(self.loop)
        self.udp_server.add_to_loop(self.loop)

    def start(self):
        assert self.loop is not None
        config = self.config

        if not config.get('dns_ipv6', False):
            asyncdns.IPV6_CONNECTION_SUPPORT = False

        logging.info(
            "local start with protocol [%s] password [%s] method [%s] obfs [%s] obfs_param [%s]"
            % (config['protocol'], config['password'], config['method'],
               config['obfs'], config['obfs_param']))

        try:
            logging.info("starting local at %s:%d" % (config['local_address'],
                                                      config['local_port']))

            signal.signal(getattr(signal, 'SIGQUIT', signal.SIGTERM), self.manager)
            signal.signal(signal.SIGINT, self.manager)

            daemon.set_user(config.get('user', None))

            # TODO: here, you will start.
            # write a manager for this try block.
            # update config
            # 用signal.alarm 定時更新

            signal.signal(signal.SIGUSR2, self.manager)
            # NOTE: if not add SIGALRM to manager, program will auto quit somehow.
            signal.signal(signal.SIGALRM, self.manager)
            # NOTE: 每次執行完網絡檢查後在重新設置alarm，而不是設置固定的interval，
            # 避免檢查時間過長導致段時間內高頻率檢查
            signal.alarm(self.alarm_period)
            # signal.setitimer(signal.ITIMER_REAL, self.alarm_period, self.alarm_period)
            threading.Thread(target=self.loop.run).start()

            # _no_conn_count = 0
            # while True:
            #     if _no_conn_count >= 5:
            #         raise Exception('connection error')
            #     if self.connectivity():
            #         print('connectivity ok')
            #         _no_conn_count = 0
            #     else:
            #         print('bad connectivity')
            #         _no_conn_count += 1
            #     time.sleep(1)



            # TODO: test use, test connection pause/resume/close
            # while True:
            #     time.sleep(5)
            #     os.kill(os.getpid(), signal.SIGUSR1)
            #     time.sleep(20)
            #     os.kill(os.getpid(), signal.SIGUSR1)
            #     time.sleep(40)
            # print('all done')

        except Exception as e:
            shell.print_exception(e)
            sys.exit(1)

    def stop(self):        # TODO: use only one single to toggle pause/resume
        """close tcp_server, udp_server."""
        os.kill(os.getpid(), signal.SIGUSR2)

    def restart(self):
        os.kill(os.getpid(), signal.SIGUSR2)

    def switch(self, config):
        self.stop()
        # FIXME: why if we remove print here, it will throw address already in use error?
        # That's weird, or just a miracle?
        # print('print it to prevent address already in use error')
        logging.info('print it to prevent address already in use error')
        self.init(config)
        self.restart()
        pass

    def manager(self, signum, frame):
        # TODO: SIGUSR1 to toggle loop status, for saving limited SIGUSR numbers.
        # SIGUSR1 is for client to updat config, SIGUSR2 is for network to switch connection.
        if signum == signal.SIGUSR2:        # pause eventloop.
            if self.loop.is_paused():
                self.loop.resume()
            else:
                self.loop.pause()
                self.tcp_server.close()       # test use, just pause, not stop
                self.udp_server.close()
        elif signum == signal.SIGQUIT or signum == signal.SIGTERM:
            logging.warn('received SIGQUIT, doing graceful shutting down..')
            self.stop()
        elif signum == signal.SIGINT:
            sys.exit(1)
        elif signum == signal.SIGALRM:
            # print('received timer alarm', time.ctime())
            # print('tring to ping baidu.com')
            # latency = self.ping('www.baidu.com')
            # print('latency to baidu.com is', latency)
            # if latency is None:
            #     self._throw_network_error_signal()

            if not self.connectivity():
                logging.info('Network error detected, tring to switch a server')
                self._throw_network_error_signal()
            signal.alarm(self.alarm_period)

    def connectivity(self, hosts=None):
        """test connectivity to host (or hosts if iterable)."""
        if hosts is None:
            hosts = ['www.google.com', 'www.github.com', 'www.baidu.com']
        elif isinstance(hosts, str):
            hosts = [hosts]
        hosts = ['www.gogole.com']
        # otherwise we assume hosts is iterable.
        for i in range(3):
            # print('range', i)
            for host in hosts:
                s = socks.socksocket()
                s.set_proxy(socks.SOCKS5, '127.0.0.1', 1080)
                s.settimeout(10)
                try:
                    s.connect((host, 80))
                    start_time = time.time()
                    s.sendall('GET / HTTP/1.1\nHost: {}\n\n'.format(host).encode('utf-8'))
                    data = s.recv(1)
                    if data:
                        # print(data, time.time() - start_time)
                        return True
                except Exception:
                    pass
                finally:
                    s.close()
        return False

    def _throw_network_error_signal(self):
        os.kill(os.getpid(), signal.SIGUSR1)

    def ping(self, host):
        """return None if cannnot connect."""
        latency = []
        for i in range(5):
            s = socks.socksocket()
            # FIXME: if set proxy, the connect time why is so small; and otherwise it's normal
            # 難道是那個時候並沒有真正連接？
            # s.setblocking(False)
            s.set_proxy(socks.SOCKS5, '127.0.0.1', 1080)        # TODO: change to local addr/port
            s.settimeout(10)
            # TODO: 解析ip，避免將解析ip的時間加入
            try:
                start_time = time.time()
                s.connect((host, 80))
                s.send(b'0')
                latency_ = time.time() - start_time
                # print('latency to {}: {}'.format(host, latency_ * 1000))
                latency.append(latency_)
                # print('sleeping')
                # time.sleep(100)
            except Exception:
                # FIXME: socks module will not throw error even no network connection!!
                # So we need other way to detect connection failure.
                pass
            finally:
                s.close()
        # return None         # TODO: test use
        if not latency:
            return None
        else:
            return 1000 * sum(latency) / len(latency)