from mmpy_bot.driver import Driver
from mmpy_bot.function import listen_to
from mmpy_bot.plugins.base import Plugin, PluginManager
from mmpy_bot.settings import Settings
from mmpy_bot.wrappers import Message

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
# import serialized_redis
  from mmpy_bot import Plugin, listen_to
  from mmpy_bot import Message
  def __init__(self, log_channel):
    self.log_channel = log_channel
    self.redis = redis.Redis(
      host="localhost", port=6379, db=0, decode_responses=True
    )
    #self.dockerclient = docker.from_env()
    self.dockerclient = aiodocker.Docker()
  def initialize(        self,
        driver: Driver,
        plugin_manager: PluginManager,
        settings: Settings
        ):
    self.driver = driver
    self.settings = settings
    self.plugin_manager = plugin_manager
    #self.ChatGPT = self.plugin_manager.plugins.ChatGPT

  
  @listen_to("^\.docker ps")
  async def dockerps(self, message: Message):
    """list docker containers"""
    containers = await self.dockerclient.containers.list()
    self.driver.reply_to(message,f"containers:")
    for c in containers:
      
      container = await self.dockerclient.containers.get(c.id)
      show = await self.dockerclient.containers.show(container.id)
      self.driver.repty_to(message, f"show?: ```{show}```")
      self.driver.reply_to(message,f"```{container.id} {container.name} {container.status}```")

  @listen_to("^\.docker run (.*)")
  async def dockerrun(self, message: Message, command: str):
    """run a docker container"""
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