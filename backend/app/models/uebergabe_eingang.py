from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UebergabeEingang(Base):
    """Ein ANGENOMMENER Uebergabebeleg (abgehakt#22, § 11).

    Nur angenommene: § 11 schuetzt die WIRKUNG ("zweimal eingelesen heisst
    einmal gewirkt"), und eine Ablehnung wirkt nicht. Ein abgelehnter Beleg
    darf erneut vorgelegt und frisch beurteilt werden.

    Gemerkt werden BEIDE Kennzeichen, nicht nur die Kennung: `beleg_id` sagt,
    ob dieser Vorgang schon lief, `beleg_sha256` sagt, ob es dieselben Bytes
    waren. Ohne den Hash waere ein Beleg mit bekannter Kennung und anderem
    Inhalt nicht von einer Wiedervorlage zu unterscheiden, und genau das ist
    BELEG_ID_WIDERSPRUCH.

    Die Tabelle ist kein Beleg im Sinne des § 147 AO, sondern das Gedaechtnis
    des Lesens. Der Beleg selbst liegt im Ordner des Absenders, und dorthin
    schreibt diese Anwendung nie.
    """

    __tablename__ = "uebergabe_eingaenge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    beleg_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    beleg_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    absender: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    nutzlast_art: Mapped[str] = mapped_column(String(32), nullable=False)
    erzeugt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    angenommen_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    # Woher die Bytes kamen. Nur Auskunft: massgeblich ist der Hash, nicht der
    # Dateiname - denselben Inhalt unter anderem Namen erkennt der Hash.
    dateiname: Mapped[Optional[str]] = mapped_column(String(255))
