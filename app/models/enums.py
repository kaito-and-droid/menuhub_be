import enum


class UserRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    cashier = "cashier"


class IngredientUnit(str, enum.Enum):
    g = "g"
    kg = "kg"
    ml = "ml"
    l = "l"
    piece = "piece"
    box = "box"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    preparing = "preparing"
    ready = "ready"
    completed = "completed"
    cancelled = "cancelled"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    bank_transfer = "bank_transfer"
    stripe = "stripe"
    paynow = "paynow"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class DeliveryType(str, enum.Enum):
    pickup = "pickup"
    delivery = "delivery"


class OrderSource(str, enum.Enum):
    web_form = "web_form"
    facebook_messenger = "facebook_messenger"
    direct_admin = "direct_admin"


class TransactionType(str, enum.Enum):
    order = "order"
    refund = "refund"
    expense = "expense"
