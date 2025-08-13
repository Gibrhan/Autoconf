import graphene
from netmiko_config import load_devices, save_devices, configure_device

class Device(graphene.ObjectType):
    id = graphene.Int()
    name = graphene.String()
    host = graphene.String()
    username = graphene.String()
    password = graphene.String()
    secret = graphene.String()
    device_type = graphene.String()

class DeviceInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    host = graphene.String(required=True)
    username = graphene.String(required=True)
    password = graphene.String(required=True)
    secret = graphene.String(required=True)
    device_type = graphene.String(required=True)

class Query(graphene.ObjectType):
    devices = graphene.List(Device)
    device_by_id = graphene.Field(Device, id=graphene.Int(required=True))

    def resolve_devices(self, info):
        devices = load_devices()
        return [Device(**dev) for dev in devices if isinstance(dev, dict)]

    def resolve_device_by_id(self, info, id):
        for dev in load_devices():
            if isinstance(dev, dict) and dev.get("id") == id:
                return Device(**dev)
        return None

class CreateDevice(graphene.Mutation):
    class Arguments:
        device_data = DeviceInput(required=True)

    device = graphene.Field(Device)

    def mutate(self, info, device_data):
        devices = load_devices()
        new_id = max([d["id"] for d in devices]) + 1 if devices else 1
        new_device = {
            "id": new_id,
            "name": device_data.name,
            "host": device_data.host,  # Cambiado
            "username": device_data.username,
            "password": device_data.password,
            "secret": device_data.secret,
            "device_type": device_data.device_type
        }
        devices.append(new_device)
        save_devices({"devices": devices})

        configure_device(new_device, ["hostname " + new_device["name"]])

        return CreateDevice(device=new_device)

class UpdateDevice(graphene.Mutation):
    class Arguments:
        id = graphene.Int(required=True)
        device_data = DeviceInput(required=True)

    device = graphene.Field(Device)

    def mutate(self, info, id, device_data):
        devices = load_devices()
        for dev in devices:
            if dev["id"] == id:
                dev["name"] = device_data.name
                dev["host"] = device_data.host  # Cambiado
                dev["username"] = device_data.username
                dev["password"] = device_data.password
                dev["secret"] = device_data.secret
                dev["device_type"] = device_data.device_type
                save_devices({"devices": devices})
                configure_device(dev, ["hostname " + dev["name"]])
                return UpdateDevice(device=dev)
        return None

class DeleteDevice(graphene.Mutation):
    class Arguments:
        id = graphene.Int(required=True)
    ok = graphene.Boolean()

    def mutate(self, info, id):
        devices = load_devices()
        devices = [d for d in devices if d["id"] != id]
        save_devices({"devices": devices})
        return DeleteDevice(ok=True)

class Mutation(graphene.ObjectType):
    create_device = CreateDevice.Field()
    update_device = UpdateDevice.Field()
    delete_device = DeleteDevice.Field()

schema = graphene.Schema(query=Query, mutation=Mutation)



