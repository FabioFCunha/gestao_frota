from django import forms
from .dossier_actions import DossierInspectionForm


CHECKLIST_ITEMS = (
    ("pneus", "Pneus e rodas"),
    ("luzes", "Faróis, lanternas e setas"),
    ("vidros", "Vidros e retrovisores"),
    ("carroceria", "Carroceria e avarias externas"),
    ("interior", "Interior, bancos e cintos"),
    ("equipamentos", "Equipamentos obrigatórios"),
    ("vazamentos", "Vazamentos aparentes"),
    ("painel", "Painel e luzes de advertência"),
)

ANSWERS = (
    ("CONFORME", "Conforme"),
    ("PROBLEMA", "Com problema"),
    ("NA", "Não se aplica"),
)


class MobileInspectionForm(DossierInspectionForm):
    inspection_moment = forms.ChoiceField(
        label="Momento da vistoria",
        choices=[
            ("", "Selecione"),
            ("SAIDA", "Saída"),
            ("RETORNO", "Retorno"),
            ("AVULSA", "Vistoria avulsa"),
        ],
        widget=forms.Select(attrs={"class": "form-input"}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mileage"].required = True
        self.fields["inspector_name"].disabled = True
        self.inspector_name = " ".join(
            part.strip()
            for part in (user.first_name or "", user.last_name or "")
            if part.strip()
        )
        self.initial["inspector_name"] = self.inspector_name
        self.fields["inspector_name"].required = False
        self.fields["inspector_name"].help_text = (
            "Nome do cadastro do usuário. Se estiver vazio, solicite "
            "ao administrador a correção do cadastro antes de salvar."
        )
        for code, label in CHECKLIST_ITEMS:
            self.fields["check_" + code] = forms.ChoiceField(
                label=label, choices=ANSWERS,
                widget=forms.RadioSelect(),
            )
            self.fields["note_" + code] = forms.CharField(
                label="Observação", required=False, max_length=2000,
                widget=forms.Textarea(attrs={
                    "class": "form-input", "rows": 2,
                    "placeholder": "Descreva o problema, se houver",
                }),
            )

    def clean(self):
        cleaned = super().clean()
        if not self.inspector_name:
            self.add_error(
                "inspector_name",
                "Seu cadastro está sem nome. Solicite ao administrador "
                "o preenchimento do nome antes de salvar a vistoria.",
            )
        elif len(self.inspector_name) > 150:
            self.add_error(
                "inspector_name",
                "O nome do cadastro excede 150 caracteres. "
                "Solicite a correção ao administrador.",
            )
        else:
            cleaned["inspector_name"] = self.inspector_name
        for code, label in CHECKLIST_ITEMS:
            if (
                cleaned.get("check_" + code) == "PROBLEMA"
                and not cleaned.get("note_" + code, "").strip()
            ):
                self.add_error(
                    "note_" + code,
                    "Descreva o problema encontrado neste item.",
                )
        return cleaned

    @property
    def checklist_rows(self):
        return [
            {
                "answer": self["check_" + code],
                "note": self["note_" + code],
            }
            for code, label in CHECKLIST_ITEMS
        ]

    def checklist_payload(self):
        return {
            "version": 1,
            "items": [
                {
                    "code": code,
                    "label": label,
                    "answer": self.cleaned_data["check_" + code],
                    "observation": self.cleaned_data.get("note_" + code, ""),
                }
                for code, label in CHECKLIST_ITEMS
            ],
        }
