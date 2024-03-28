from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
import ntplib
from time import ctime
from textwrap import dedent
import socket


class Ntp(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(
        self, driver: Driver, plugin_manager: PluginManager, settings: Settings
    ):
        super().initialize(driver, plugin_manager, settings)

    def get_ntp_response(self, server):
        c = ntplib.NTPClient()
        try:
            response = c.request(server)
        except ntplib.NTPException as e:
            raise e
        return response

    def get_ntp_response_from_all(self, servers):
        # get all the ntp servers from the hostname
        ips = socket.gethostbyname_ex(servers)[2]
        responses = []
        for s in ips:
            try:
                response = self.get_ntp_response(s)
                responses.append((s, response))
            except ntplib.NTPException as e:
                responses.append((s, {"error": str(e)}))
        return responses

    @listen_to(r"^\.ntptest ([\s\S]*)")
    async def ntp_test(self, message: Message, server: str):
        """function to test ntp server"""
        self.driver.reply_to(
            message,
            f"hostname: {server}, ips: {', '.join(socket.gethostbyname_ex(server)[2])}",
        )
        responses = self.get_ntp_response_from_all(server)
        for s, response in responses:
            if not isinstance(response, ntplib.NTPStats) and "error" in response:
                self.driver.reply_to(message, response["error"])
                continue
            my_time = ctime()
            tx_time = ctime(response.tx_time)
            offset = response.offset
            delay = response.delay
            stratum = ntplib.stratum_to_text(response.stratum)
            mode = ntplib.mode_to_text(response.mode)
            leap = ntplib.leap_to_text(response.leap)
            ref_id_str = ntplib.ref_id_to_text(response.ref_id, response.stratum)
            self.driver.reply_to(
                message,
                dedent(
                    f"""\
                    my time: {my_time}
                    ntp time: {tx_time}
                    ntp offset: {offset}
                    ntp delay: {delay}
                    stratum: {stratum}
                    mode: {mode}
                    leap: {leap}
                    ref id: {ref_id_str}
                    server: {s}
                    """
                ),
            )

    @listen_to(r"^\.ntpcompare ([\s\S]*) ([\s\S]*)")
    async def ntp_compare(self, message: Message, server1: str, server2: str):
        """function to compare ntp servers"""
        self.driver.reply_to(
            message,
            f"ntp1 hostname: {server1}, ips: {', '.join(socket.gethostbyname_ex(server1)[2])}",
        )
        self.driver.reply_to(
            message,
            f"ntp2 hostname: {server2}, ips: {', '.join(socket.gethostbyname_ex(server2)[2])}",
        )
        responses1 = self.get_ntp_response_from_all(server1)
        responses2 = self.get_ntp_response_from_all(server2)
        for (s1, response1), (s2, response2) in zip(responses1, responses2):
            if not isinstance(response1, ntplib.NTPStats) and "error" in response1:
                self.driver.reply_to(message, response1["error"])
                continue
            if not isinstance(response2, ntplib.NTPStats) and "error" in response2:
                self.driver.reply_to(message, response2["error"])
                continue
            offset1 = response1.offset
            offset2 = response2.offset
            delay1 = response1.delay
            delay2 = response2.delay
            stratum1 = ntplib.stratum_to_text(response1.stratum)
            stratum2 = ntplib.stratum_to_text(response2.stratum)
            ref_id_str1 = ntplib.ref_id_to_text(response1.ref_id, response1.stratum)
            ref_id_str2 = ntplib.ref_id_to_text(response2.ref_id, response2.stratum)

            self.driver.reply_to(
                message,
                dedent(
                    f"""\
                    ntp1 offset: {offset1}
                    ntp2 offset: {offset2}
                    offset diff: {offset1 - offset2}
                    ntp1 delay: {delay1}
                    ntp2 delay: {delay2}
                    delay diff: {delay1 - delay2}
                    ntp1 stratum: {stratum1}
                    ntp2 stratum: {stratum2}
                    ntp1 ref id: {ref_id_str1}
                    ntp2 ref id: {ref_id_str2}
                    server1: {s1}
                    server2: {s2}
                    """
                ),
            )

    @listen_to(r"^\.ntplookup ([\s\S]*)")
    async def ntp_lookup(self, message: Message, server: str):
        """function to get all ntp servers from a dns record"""
        try:
            servers = socket.gethostbyname_ex(server)
            servers = servers[2]

            self.driver.reply_to(message, f"hostname: {server}, ips: {servers}")
        except Exception as e:  # pylint: disable=broad-except
            self.driver.reply_to(message, f"error: {str(e)}")
