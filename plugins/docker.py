from mmpy_bot.function import listen_to
from mmpy_bot.wrappers import Message
from plugins.base import PluginLoader
from environs import Env
env = Env()

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
class Docker(PluginLoader):
  def __init__(self):
    # initialize parent class
    super().__init__()
    self.dockerclient = aiodocker.Docker()
  # help
  @listen_to("^\.docker help")
  async def dockerhelp(self, message: Message):
    """docker help"""
    messagetxt = "```"
    messagetxt += ".docker ps\n"
    messagetxt += ".docker run <command>\n"
    messagetxt += ".docker stop <container_id>\n"
    messagetxt += ".docker rm <container_id>\n"
    messagetxt += ".docker logs <container_id>\n"
    messagetxt += ".docker image pull <image>\n"
    messagetxt += ".docker image ls\n"
    messagetxt += "```"
    self.driver.reply_to(message, f"{messagetxt}")
  @listen_to("^\.docker ps")
  async def dockerps(self, message: Message):
    """list docker containers"""
    if not self.users.is_admin(message.sender_name):
      return
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
    if not self.users.is_admin(message.sender_name):
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
    if not self.users.is_admin(message.sender_name):
      return
    container = await self.dockerclient.containers.get(container_id)
    self.driver.reply_to(message, f"stopping ```{container.id}```")
    await container.stop()
    self.driver.reply_to(message, f"stopped ```{container.id}```")

  @listen_to("^\.docker rm (.*)")
  async def dockerrm(self, message: Message, container_id: str):
    """remove a docker container"""
    if not self.users.is_admin(message.sender_name):
      return
    container = await self.dockerclient.containers.get(container_id)
    self.driver.reply_to(message, f"removing ```{container.id}```")
    await container.delete()
    self.driver.reply_to(message, f"removed ```{container.id}```")

  @listen_to("^\.docker logs (.*)")
  async def dockerlogs(self, message: Message, container_id: str):
    """logs from a docker container"""
    if not self.users.is_admin(message.sender_name):
      return
    container = await self.dockerclient.containers.get(container_id)
    logs = await container.log(stdout=True)
    self.driver.reply_to(message,''.join(logs))

  @listen_to("^\.docker image pull (.*)")
  async def dockerimagepull(self, message: Message, image: str):
    if not self.users.is_admin(message.sender_name):
      return
    """pull a docker image"""
    await self.dockerclient.images.pull(image)
    self.driver.reply_to(message, f"pulled ```{image}```")

  @listen_to("^\.docker image ls")
  async def dockerimagels(self, message: Message):
    """list docker images"""
    if not self.users.is_admin(message.sender_name):
      return
    images = await self.dockerclient.images.list()
    self.driver.reply_to(message,f"images:")
    for image in images:
      self.driver.reply_to(message,f"```{image}```")