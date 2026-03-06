# Mockup Compositor — PhotoSì

App Streamlit per applicare grafiche su template multi-formato ed esportare in ZIP.

## Setup locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy su Streamlit Cloud

1. Pusha su GitHub
2. Vai su [share.streamlit.io](https://share.streamlit.io)
3. Collega il repo e imposta `app.py` come entry point

## Struttura cartella template

```
preview app/
└── printbox/
    ├── coords.json        ← generato automaticamente dall'app
    ├── Orizzontale/
    │   ├── template1.jpg
    │   └── ...
    ├── Quadrato/
    └── Verticali/
```

## Note

- Le coordinate vengono salvate in `coords.json` nella cartella printbox
- Su Streamlit Cloud la cartella template va caricata tramite l'uploader
