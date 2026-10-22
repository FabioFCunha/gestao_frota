"""Campos da frente do modelo numerado, após reconhecimento do leiaute."""
import re

from .cnh_legacy import _cpf_digits, _name


def extract_front_fields(image, read_region):
    result = {}
    # Somente o campo de registro: preserva os zeros à esquerda e exclui
    # números da MRZ, do QR e da impressão vertical.
    number = re.sub(r"\D", "", read_region(image, (.667, .604, .825, .647)))
    if len(number) == 11:
        result["cnh_number"] = number
    cpf = _cpf_digits(read_region(image, (.462, .605, .638, .647)))
    if cpf:
        result["cpf"] = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
    father = _name(read_region(image, (.462, .773, .975, .84)))
    mother = _name(read_region(image, (.462, .861, .975, .97)))
    # Não adivinha a filiação quando só um dos nomes foi reconhecido.
    if father and mother:
        result.update(father_name=father, mother_name=mother)
    return result
