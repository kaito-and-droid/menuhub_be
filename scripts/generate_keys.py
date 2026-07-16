"""Generate the RS256 keypair used to sign JWTs. Run once per environment:

    uv run python scripts/generate_keys.py [output_dir=keys]
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (out_dir / "jwt_private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (out_dir / "jwt_public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"Wrote {out_dir}/jwt_private.pem and {out_dir}/jwt_public.pem")


if __name__ == "__main__":
    generate(Path(sys.argv[1] if len(sys.argv) > 1 else "keys"))
