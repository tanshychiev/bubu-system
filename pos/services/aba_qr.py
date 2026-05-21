import base64
import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal

import requests
from django.conf import settings

from pos.models import ABAPaymentSession


PAYWAY_SANDBOX_QR_URL = "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/generate-qr"
PAYWAY_SANDBOX_CHECK_URL = "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/check-transaction-2"


def _payway_req_time():
    return time.strftime("%Y%m%d%H%M%S")


def _base64_json(data):
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def _make_hash(payload, api_key):
    """
    PayWay requires hash. Confirm exact hash fields with your PayWay account docs.
    This common format signs concatenated values.
    """
    raw = "".join(str(v or "") for v in payload.values())
    digest = hmac.new(
        api_key.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha512,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def create_real_aba_payment(*, branch, cashier, amount: Decimal):
    """
    Real ABA PayWay Dynamic QR.
    Need these in settings.py:
        PAYWAY_MERCHANT_ID
        PAYWAY_API_KEY
        PAYWAY_CALLBACK_URL
        PAYWAY_SANDBOX = True
    """

    merchant_id = settings.PAYWAY_MERCHANT_ID
    api_key = settings.PAYWAY_API_KEY
    callback_url = settings.PAYWAY_CALLBACK_URL

    tran_id = uuid.uuid4().hex[:20]
    req_time = _payway_req_time()

    items = _base64_json([
        {
            "name": f"BUBU POS {branch.name}",
            "quantity": 1,
            "price": float(amount),
        }
    ])

    callback_url_base64 = base64.b64encode(
        callback_url.encode("utf-8")
    ).decode("utf-8")

    payload = {
        "req_time": req_time,
        "merchant_id": merchant_id,
        "tran_id": tran_id,
        "first_name": "BUBU",
        "last_name": "Pet Store",
        "email": "bubu@example.com",
        "phone": "012345678",
        "amount": float(amount),
        "purchase_type": "purchase",
        "payment_option": "abapay_khqr",
        "items": items,
        "currency": "USD",
        "callback_url": callback_url_base64,
        "return_deeplink": None,
        "custom_fields": None,
        "return_params": None,
        "payout": None,
        "lifetime": 6,
        "qr_image_template": "template3_color",
    }

    payload["hash"] = _make_hash(payload, api_key)

    url = PAYWAY_SANDBOX_QR_URL if getattr(settings, "PAYWAY_SANDBOX", True) else settings.PAYWAY_QR_URL

    response = requests.post(url, json=payload, timeout=20)
    data = response.json()

    status = data.get("status", {})
    if str(status.get("code")) not in ["0", "00"]:
        raise Exception(f"PayWay QR failed: {data}")

    qr_image = data.get("qrImage", "")
    qr_string = data.get("qrString", "")

    session = ABAPaymentSession.objects.create(
        branch=branch,
        cashier=cashier,
        amount=amount,
        session_key=tran_id,
        status=ABAPaymentSession.STATUS_WAITING,
        qr_image_url=qr_image,
        qr_text=qr_string,
        aba_tran_id=tran_id,
        aba_response=data,
    )

    return session


def check_real_aba_payment(session: ABAPaymentSession):
    merchant_id = settings.PAYWAY_MERCHANT_ID
    api_key = settings.PAYWAY_API_KEY

    req_time = _payway_req_time()

    payload = {
        "req_time": req_time,
        "merchant_id": merchant_id,
        "tran_id": session.aba_tran_id,
    }

    payload["hash"] = _make_hash(payload, api_key)

    url = PAYWAY_SANDBOX_CHECK_URL if getattr(settings, "PAYWAY_SANDBOX", True) else settings.PAYWAY_CHECK_URL

    response = requests.post(url, json=payload, timeout=20)
    data = response.json()

    pay_data = data.get("data", {})
    status_text = str(pay_data.get("payment_status", "")).upper()
    status_code = str(pay_data.get("payment_status_code", ""))

    paid_amount = Decimal(str(pay_data.get("payment_amount") or "0"))

    paid = (
        status_text == "APPROVED"
        or status_code == "0"
    )

    amount_correct = paid_amount == session.amount

    if paid and amount_correct:
        session.status = ABAPaymentSession.STATUS_PAID
        session.aba_response = data
        session.save(update_fields=["status", "aba_response", "updated_at"])

    return {
        "paid": paid and amount_correct,
        "amount_correct": amount_correct,
        "paid_amount": paid_amount,
        "expected_amount": session.amount,
        "raw": data,
    }