from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message
from plugins.common import Helper
from plugins.users import Users
from environs import Env
env = Env()

import redis
import aiodocker

CONTAINER_CONFIG = {
     "Cmd": ["/bin/ls"],
     "Image": "ubuntu:latest",
     "AttachStdin": False,
     "AttachStdout": True,
     "AttachStderr": True,
     "Tty": False,
     "OpenStdin": False,
}
class Docker(Plugin):
  def __init__(self):
    self.dockerclient = aiodocker.Docker()
  def initialize(        self,
        driver: Driver,
        plugin_manager: PluginManager,
        settings: Settings
        ):
    self.driver = driver
    self.settings = settings
    self.plugin_manager = plugin_manager
    self.helper = Helper(self.driver)
    self.users = Users(self.driver, self.plugin_manager, self.settings)

  @listen_to("^\.plugins list")
  async def pluginslist(self, message: Message):
    """list plugins"""
    plugins = self.plugin_manager.plugins
    self.driver.reply_to(message,f"plugins:")
    for plugin in plugins:
      info = dir(plugin)
      classname = plugin.__class__
      self.driver.reply_to(message,f"```{info}```")
  
  @listen_to("^\.docker ps")
  async def dockerps(self, message: Message):
    """list docker containers"""
    containers = await self.dockerclient.containers.list()
    self.driver.reply_to(message,f"containers:")
    for c in containers:
      container = await self.dockerclient.containers.get(c.id)
      info = await container.show()
      # load json into dict
#      import json
#      info = json.loads(info)

      self.driver.reply_to(message,f"```{info['Id']} {info['State']['Status']}```")

  @listen_to("^\.docker run (.*)")
  async def dockerrun(self, message: Message, command: str):
    """run a docker container"""
    if self.helper.is_admin(message.sender_name) == True:
      self.driver.reply_to(message, f"you are not an admin")
      return
    config = CONTAINER_CONFIG
    config["Cmd"] = command.split(" ")
    # pull image 
    image = config["Image"]
    await self.dockerclient.images.pull(image)
    container = await self.dockerclient.containers.create(config=config)
    self.driver.reply_to(message, f"starting ```{container.id}```")
    await container.start()
    self.driver.reply_to(message, f"started ```{container.id}```")
    logs = await container.log(stdout=True)
    self.driver.reply_to(message,''.join(logs))

  @listen_to("^\.docker stop (.*)")
  async def dockerstop(self, message: Message, container_id: str):
    """stop a docker container"""
    container = await self.dockerclient.containers.get(container_id)
    self.driver.reply_to(message, f"stopping ```{container.id}```")
    await container.stop()
    self.driver.reply_to(message, f"stopped ```{container.id}```")

  @listen_to("^\.docker rm (.*)")
  async def dockerrm(self, message: Message, container_id: str):
    """remove a docker container"""
    container = await self.dockerclient.containers.get(container_id)
    self.driver.reply_to(message, f"removing ```{container.id}```")
    await container.delete()
    self.driver.reply_to(message, f"removed ```{container.id}```")

  @listen_to("^\.docker logs (.*)")
  async def dockerlogs(self, message: Message, container_id: str):
    """logs from a docker container"""
    container = await self.dockerclient.containers.get(container_id)
    logs = await container.log(stdout=True)
    self.driver.reply_to(message,''.join(logs))

  @listen_to("^\.docker image pull (.*)")
  async def dockerimagepull(self, message: Message, image: str):
    """pull a docker image"""
    await self.dockerclient.images.pull(image)
    self.driver.reply_to(message, f"pulled ```{image}```")

  @listen_to("^\.docker image ls")
  async def dockerimagels(self, message: Message):
    """list docker images"""
    images = await self.dockerclient.images.list()
    self.driver.reply_to(message,f"images:")
    for image in images:
      self.driver.reply_to(message,f"```{image} {image.tag}```")