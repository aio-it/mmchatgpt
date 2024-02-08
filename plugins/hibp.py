from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from mmpy_bot.driver import Driver
from mmpy_bot.plugins.base import PluginManager
from mmpy_bot.settings import Settings
from plugins.base import PluginLoader
import hibpwned

# load env
from environs import Env


class HIPB(PluginLoader):
    def __init__(self):
        super().__init__()

    def initialize(
        self, driver: Driver, plugin_manager: PluginManager, settings: Settings
    ):
        super().initialize(driver, plugin_manager, settings)
        # api key from env HIBP_API_KEY
        self.api_key = Env().str("HIBP_API_KEY")
        self.disabled = False
        if not self.api_key:
            self.helper.slog("HIBP_API_KEY not found in .env")
            self.disabled = True

    @listen_to(r"^\.hibp ([\s\S]*)")
    @listen_to(r"^\.haveibeenpwned ([\s\S]*)")
    async def hibp(self, message: Message, text: str):
        """function: Check if an email or password has been pwned using the Have I Been Pwned API"""
        if self.disabled:
            self.driver.reply_to(
                message, "The HIBP API key is not set. Please set it in the .env file"
            )
            return
        # check if the users is an user
        if self.users.is_user(message.sender_name):
            # load the hibpwned module
            hibp = hibpwned.Pwned(text, "hibpwned", self.api_key)
            # search all breaches
            result = hibp.search_all_breaches()
            # if there are breaches its a list
            if isinstance(result, list):
                # loop over result and convert any links to markdown
                # <a href=".*" target="_blank" rel="noopener">.*</a>
                for r in result:
                    r["Description"] = (
                        r["Description"]
                        .replace("<a href=", "[")
                        .replace(' target="_blank" rel="noopener">', "]")
                        .replace("</a>", "")
                    )

                # format result with title, Breachdate, domain, Description and dataclasses
                result = "\n\n".join(
                    [
                        f"\n**{r['Title']}**\n```\nBreach Date: {r['BreachDate']}\nDomain: {r['Domain']}\nDescription: {r['Description']}\nData Classes: {', '.join(r['DataClasses'])}\n```"
                        for r in result
                    ]
                )

                # send the breaches
                self.helper.slog(
                    f"user {message.sender_name} used .hibp {text} and got breaches"
                )
                self.driver.reply_to(message, f"HIBP Results for {text}:\n{result}")
            else:
                self.helper.slog(
                    f"user {message.sender_name} used .hibp {text} and got no breaches: {result}"
                )
                # if there are no breaches
                self.driver.reply_to(message, f"No breaches found for {text}")


# example result
# [
#     {
#         "Name": "Cit0day",
#         "Title": "Cit0day",
#         "Domain": "cit0day.in",
#         "BreachDate": "2020-11-04",
#         "AddedDate": "2020-11-19T08:07:33Z",
#         "ModifiedDate": "2020-11-19T08:07:33Z",
#         "PwnCount": 226883414,
#         "Description": 'In November 2020, <a href="https://www.troyhunt.com/inside-the-cit0day-breach-collection" target="_blank" rel="noopener">a collection of more than 23,000 allegedly breached websites known as Cit0day were made available for download on several hacking forums</a>. The data consisted of 226M unique email address alongside password pairs, often represented as both password hashes and the cracked, plain text versions. Independent verification of the data established it contains many legitimate, previously undisclosed breaches. The data was provided to HIBP by <a href="https://dehashed.com/" target="_blank" rel="noopener">dehashed.com</a>.',
#         "LogoPath": "https://haveibeenpwned.com/Content/Images/PwnedLogos/List.png",
#         "DataClasses": ["Email addresses", "Passwords"],
#         "IsVerified": False,
#         "IsFabricated": False,
#         "IsSensitive": False,
#         "IsRetired": False,
#         "IsSpamList": False,
#         "IsMalware": False,
#         "IsSubscriptionFree": False,
#     },
#     {
#         "Name": "Collection1",
#         "Title": "Collection #1",
#         "Domain": "",
#         "BreachDate": "2019-01-07",
#         "AddedDate": "2019-01-16T21:46:07Z",
#         "ModifiedDate": "2019-01-16T21:50:21Z",
#         "PwnCount": 772904991,
#         "Description": 'In January 2019, a large collection of credential stuffing lists (combinations of email addresses and passwords used to hijack accounts on other services) was discovered being distributed on a popular hacking forum. The data contained almost 2.7 <em>billion</em> records including 773 million unique email addresses alongside passwords those addresses had used on other breached services. Full details on the incident and how to search the breached passwords are provided in the blog post <a href="https://www.troyhunt.com/the-773-million-record-collection-1-data-reach" target="_blank" rel="noopener">The 773 Million Record "Collection #1" Data Breach</a>.',
#         "LogoPath": "https://haveibeenpwned.com/Content/Images/PwnedLogos/List.png",
#         "DataClasses": ["Email addresses", "Passwords"],
#         "IsVerified": False,
#         "IsFabricated": False,
#         "IsSensitive": False,
#         "IsRetired": False,
#         "IsSpamList": False,
#         "IsMalware": False,
#         "IsSubscriptionFree": False,
#     },
#     {
#         "Name": "GeekedIn",
#         "Title": "GeekedIn",
#         "Domain": "geekedin.net",
#         "BreachDate": "2016-08-15",
#         "AddedDate": "2016-11-17T19:44:24Z",
#         "ModifiedDate": "2022-03-06T05:21:27Z",
#         "PwnCount": 1073164,
#         "Description": 'In August 2016, the technology recruitment site GeekedIn left a MongoDB database exposed and over 8M records were extracted by an unknown third party. The breached data was originally scraped from GitHub in violation of their terms of use and contained information exposed in public profiles, including over 1 million members\' email addresses. Full details on the incident (including how impacted members can see their leaked data) are covered in the blog post on <a href="https://www.troyhunt.com/8-million-github-profiles-were-leaked-from-geekedins-mongodb-heres-how-to-see-yours" target="_blank" rel="noopener">8 million GitHub profiles were leaked from GeekedIn\'s MongoDB - here\'s how to see yours</a>.',
#         "LogoPath": "https://haveibeenpwned.com/Content/Images/PwnedLogos/GeekedIn.png",
#         "DataClasses": [
#             "Email addresses",
#             "Geographic locations",
#             "Names",
#             "Professional skills",
#             "Usernames",
#             "Years of professional experience",
#         ],
#         "IsVerified": True,
#         "IsFabricated": False,
#         "IsSensitive": False,
#         "IsRetired": False,
#         "IsSpamList": False,
#         "IsMalware": False,
#         "IsSubscriptionFree": False,
#     },
#     {
#         "Name": "Patreon",
#         "Title": "Patreon",
#         "Domain": "patreon.com",
#         "BreachDate": "2015-10-01",
#         "AddedDate": "2015-10-02T02:29:20Z",
#         "ModifiedDate": "2021-08-10T06:52:47Z",
#         "PwnCount": 2330382,
#         "Description": 'In October 2015, the crowdfunding site <a href="http://www.zdnet.com/article/patreon-hacked-anonymous-patrons-exposed/" target="_blank" rel="noopener">Patreon was hacked</a> and over 16GB of data was released publicly. The dump included almost 14GB of database records with more than 2.3M unique email addresses,  millions of personal messages and passwords stored as bcrypt hashes.',
#         "LogoPath": "https://haveibeenpwned.com/Content/Images/PwnedLogos/Patreon.png",
#         "DataClasses": [
#             "Email addresses",
#             "Passwords",
#             "Payment histories",
#             "Physical addresses",
#             "Private messages",
#             "Website activity",
#         ],
#         "IsVerified": True,
#         "IsFabricated": False,
#         "IsSensitive": False,
#         "IsRetired": False,
#         "IsSpamList": False,
#         "IsMalware": False,
#         "IsSubscriptionFree": False,
#     },
#     {
#         "Name": "BVD",
#         "Title": "Public Business Data",
#         "Domain": "bvdinfo.com",
#         "BreachDate": "2021-08-19",
#         "AddedDate": "2023-10-09T07:05:10Z",
#         "ModifiedDate": "2023-12-06T22:45:20Z",
#         "PwnCount": 27917714,
#         "Description": 'In approximately August 2021, <a href="https://kaduu.io/blog/2022/02/04/us-strategic-company-bureau-van-dijk-hacked/" target="_blank" rel="noopener">hundreds of gigabytes of business data collated from public sources was obtained and later published to a popular hacking forum</a>. Sourced from a customer of Bureau van Dijk\'s (BvD) "Orbis" product, the corpus of data released contained hundreds of millions of lines about corporations and individuals, including personal information such as names and dates of birth. The data also included 28M unique email addresses along with physical addresses (presumedly corporate locations), phone numbers and job titles. There was no unauthorised access to BvD\'s systems, nor did the incident expose any of their or parent company\'s Moody\'s clients.',
#         "LogoPath": "https://haveibeenpwned.com/Content/Images/PwnedLogos/List.png",
#         "DataClasses": [
#             "Dates of birth",
#             "Email addresses",
#             "Job titles",
#             "Names",
#             "Phone numbers",
#             "Physical addresses",
#         ],
#         "IsVerified": True,
#         "IsFabricated": False,
#         "IsSensitive": False,
#         "IsRetired": False,
#         "IsSpamList": False,
#         "IsMalware": False,
#         "IsSubscriptionFree": False,
#     },
#     {
#         "Name": "Thingiverse",
#         "Title": "Thingiverse",
#         "Domain": "thingiverse.com",
#         "BreachDate": "2020-10-13",
#         "AddedDate": "2021-10-14T10:02:04Z",
#         "ModifiedDate": "2021-10-14T10:02:04Z",
#         "PwnCount": 228102,
#         "Description": 'In October 2021, a database backup taken from the 3D model sharing service <a href="https://www.databreachtoday.com/thingiverse-data-leak-affects-25-million-subscribers-a-17729" target="_blank" rel="noopener">Thingiverse began extensively circulating within the hacking community</a>. Dating back to October 2020, the 36GB file contained 228 thousand unique email addresses, mostly alongside comments left on 3D models. The data also included usernames, IP addresses, full names and passwords stored as either unsalted SHA-1 or bcrypt hashes. In some cases, physical addresses was also exposed. Thingiverse\'s owner, MakerBot, is aware of the incident but at the time of writing, is yet to issue a disclosure statement. The data was provided to HIBP by <a href="https://dehashed.com/" target="_blank" rel="noopener">dehashed.com</a>.',
#         "LogoPath": "https://haveibeenpwned.com/Content/Images/PwnedLogos/Thingiverse.png",
#         "DataClasses": [
#             "Dates of birth",
#             "Email addresses",
#             "IP addresses",
#             "Names",
#             "Passwords",
#             "Physical addresses",
#             "Usernames",
#         ],
#         "IsVerified": True,
#         "IsFabricated": False,
#         "IsSensitive": False,
#         "IsRetired": False,
#         "IsSpamList": False,
#         "IsMalware": False,
#         "IsSubscriptionFree": False,
#     },
# ]
