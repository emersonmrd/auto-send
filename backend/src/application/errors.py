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


class BroadcastNotFoundError(LookupError):
    """O broadcast pedido pelo caso de uso não existe."""


class InvalidScheduleFormatError(ValueError):
    """scheduled_at não é uma data ISO-8601."""

    def __init__(self) -> None:
        super().__init__("Invalid scheduled_at ISO-8601 format")


class BroadcastAbortedError(Exception):
    """O usuário interrompeu o disparo em voo; as entregas parciais ficam gravadas."""

    def __init__(self) -> None:
        super().__init__("Broadcast cancelled by user")
