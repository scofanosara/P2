# Simulador Jurídico para Estudantes

Aplicativo para treinar argumentação jurídica usando casos reais (proposições da Câmara) ou casos locais definidos pelo grupo.

## Estrutura
```
simulador_juridico_estudantes/
├── app.py
├── utils.py
├── data/
│   └── principios.csv
├── requirements.txt
└── README.md
```

## Como rodar (local)
1. Crie um ambiente virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   venv\\Scripts\\activate    # Windows
   ```
2. Instale dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Rode o app:
   ```bash
   streamlit run app.py
   ```

## Uso principal
- Marque "Buscar proposições da Câmara" no sidebar e pesquise por termo (ex.: "saúde").
- Selecione uma proposição retornada.
- Clique em "Mapear automaticamente princípios" para gerar sugestões a partir da base local.
- Escolha acusação ou defesa, escreva argumentos e clique em "Avaliar argumentação".

## Observações
- A API da Câmara exige internet para funcionar.
- O mapeamento automático é heurístico (palavras-chave). Revise manualmente as sugestões.
