
import re
from decimal import Decimal, InvalidOperation


def normalize_km(valor: str | int | float | Decimal | None) -> Decimal | None:
    """
    Normaliza valores de quilometragem provenientes do Hórus.

    Exemplos de separador de milhar:
        "54900"       -> 54900
        "54 900"      -> 54900
        "35 291"      -> 35291
        "46.980"      -> 46980
        "46.   980"   -> 46980
        "123.456"     -> 123456
        "1 234 567"   -> 1234567
        "1.234.567"   -> 1234567
        "1234.567"    -> 1234567
        "9.850"       -> 9850

    Exemplos de decimal:
        "10.5"        -> 10.5
        "10.7"        -> 10.7
        "10.8"        -> 10.8
        "35.7"        -> 35.7
        "40.00"       -> 40.00
        "49.00"       -> 49.00
        "650.00"      -> 650.00
        "706.00"      -> 706.00
        "870.0"       -> 870.0
        "935.3"       -> 935.3

    O valor original continua armazenado no BDT como texto.
    Esta função apenas normaliza o valor para cálculos.
    """

    if valor is None:
        return None

    texto = str(valor).strip()

    if not texto:
        return None

    # Valores numéricos já tipados.
    if isinstance(valor, Decimal):
        return valor

    if isinstance(valor, int):
        return Decimal(valor)

    if isinstance(valor, float):
        try:
            return Decimal(str(valor))
        except InvalidOperation:
            return None

    # Somente números inteiros.
    #
    # Exemplo:
    # "54900" -> 54900
    if re.fullmatch(r"\d+", texto):
        return Decimal(texto)

    # Separador de milhar usando espaços.
    #
    # Aceita:
    # "54 900"
    # "35 291"
    # "1 234 567"
    if re.fullmatch(r"\d+(?:\s+\d{3})+", texto):
        return Decimal(re.sub(r"\s+", "", texto))

    if "." in texto:
        # Remove espaços ao redor dos pontos para preservar
        # formatos antigos como:
        #
        # "46.   980" -> "46.980"
        texto_pontos = re.sub(r"\s*\.\s*", ".", texto)

        partes = texto_pontos.split(".")

        # ---------------------------------------------------------
        # Separador de milhar
        # ---------------------------------------------------------
        #
        # Exemplos:
        # 46.980
        # 123.456
        # 1.234.567
        # 1234.567
        # 9.850
        #
        # Todos os grupos depois do primeiro possuem exatamente
        # três dígitos.
        if (
            len(partes) >= 2
            and partes[0].isdigit()
            and all(
                parte.isdigit() and len(parte) == 3
                for parte in partes[1:]
            )
        ):
            return Decimal("".join(partes))

        # ---------------------------------------------------------
        # Decimal
        # ---------------------------------------------------------
        #
        # Aqui deliberadamente aceitamos apenas 1 ou 2 casas
        # decimais, que são os formatos encontrados no Hórus.
        #
        # Exemplos:
        # 10.5
        # 870.0
        # 935.3
        # 40.00
        # 650.00
        if (
            len(partes) == 2
            and partes[0].isdigit()
            and partes[1].isdigit()
            and 1 <= len(partes[1]) <= 2
        ):
            try:
                return Decimal(texto_pontos)
            except InvalidOperation:
                return None

    return None

