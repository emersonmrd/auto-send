class ProfileNotFoundError(LookupError):
    """O perfil pedido pelo caso de uso não existe."""


class ChannelNotFoundError(LookupError):
    """O canal pedido pelo caso de uso não existe."""


class ChannelAlreadyRegisteredError(ValueError):
    """O chat já está vinculado a outro canal do mesmo perfil."""

    def __init__(self) -> None:
        super().__init__("Channel already registered for this profile")


class ChannelDispatchingError(ValueError):
    """Há um disparo em andamento para o canal: trocar o chat_id agora deixaria entregas pela metade."""

    def __init__(self) -> None:
        super().__init__("There is a broadcast currently dispatching. Wait for it to finish and try again.")
