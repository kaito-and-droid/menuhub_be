"""PayNow EMVCo merchant-presented QR payload generation (Singapore).

Static generation only — payment confirmation is manual ("Mark paid" in the
dashboard). No PSP involved.
"""

from app.models import Order, Shop


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) as required by EMVCo."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def paynow_config(shop: Shop) -> tuple[str, str] | None:
    settings = shop.settings or {}
    proxy_type = settings.get("paynow_proxy_type")
    proxy_value = settings.get("paynow_proxy_value")
    if proxy_type in ("UEN", "MOBILE") and proxy_value:
        return proxy_type, str(proxy_value)
    return None


def build_paynow_qr(shop: Shop, order: Order) -> str | None:
    config = paynow_config(shop)
    if config is None:
        return None
    proxy_type, proxy_value = config
    if proxy_type == "MOBILE":
        proxy_flag = "0"
        if not proxy_value.startswith("+"):
            proxy_value = f"+65{proxy_value.lstrip('0')}"
    else:
        proxy_flag = "2"

    merchant_info = (
        _tlv("00", "SG.PAYNOW")
        + _tlv("01", proxy_flag)
        + _tlv("02", proxy_value)
        + _tlv("03", "0")  # amount not editable by payer
    )
    reference = order.order_number.lstrip("#") or "0"
    payload = (
        _tlv("00", "01")  # payload format indicator
        + _tlv("01", "12")  # dynamic QR (one transaction)
        + _tlv("26", merchant_info)
        + _tlv("52", "0000")  # merchant category code
        + _tlv("53", "702")  # SGD
        + _tlv("54", f"{float(order.total_amount):.2f}")
        + _tlv("58", "SG")
        + _tlv("59", shop.shop_name[:25])
        + _tlv("60", "Singapore")
        + _tlv("62", _tlv("01", reference))  # bill/reference number
        + "6304"  # CRC tag+length, included in the checksum input
    )
    return payload + f"{crc16_ccitt(payload.encode('ascii', 'ignore')):04X}"
