# MCP Magistrat Civil

Serveurs MCP (Model Context Protocol) et compétence de raisonnement juridique pour accéder aux bases juridiques françaises et structurer l'analyse d'un magistrat civil.

Ce projet permet à Claude d'accéder à :
- **Judilibre** : jurisprudence de la Cour de cassation et des juridictions du fond
- **Légifrance** : codes, lois, décrets et Journal Officiel
- **Raisonnement juridique** : méthodologie du syllogisme judiciaire selon les fiches de l'ENM/Cour de cassation

## Structure du dépôt

```
mcp-droit-francais/
├── servers/
│   ├── judilibre_mcp_server.py     # Serveur MCP Judilibre
│   └── legifrance_mcp_server.py    # Serveur MCP Légifrance
├── skills/
│   └── raisonnement-juridique/
│       ├── SKILL.md                # Compétence principale
│       └── references/             # Fichiers de référence détaillés
│           ├── hierarchie-decisions.md
│           ├── syllogisme-juridique.md
│           ├── office-du-juge.md
│           ├── structure-jugement.md
│           └── exemples-motivations.md
├── requirements.txt
├── .env.example
└── README.md
```

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/votre-username/mcp-magistrat-civil.git
cd mcp-magistrat-civil
```

### 2. Créer un environnement virtuel (recommandé)

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# ou
.\venv\Scripts\activate   # Windows
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement

Copier le fichier d'exemple et le compléter :

```bash
cp .env.example .env
```

Éditer `.env` avec vos identifiants :

```env
# Judilibre (obligatoire)
JUDILIBRE_API_KEY=votre_cle_api_judilibre

# Légifrance (obligatoire)
PISTE_CLIENT_ID=votre_client_id
PISTE_CLIENT_SECRET=votre_client_secret
```

#### Obtenir les identifiants API

**Judilibre** (obligatoire) :
1. Créer un compte sur [PISTE](https://piste.gouv.fr/)
2. Créer une application
3. S'abonner à l'API "Judilibre"
4. Récupérer le `api_key`

**Légifrance** (obligatoire) :
1. Créer un compte sur [PISTE](https://piste.gouv.fr/)
2. Créer une application
3. S'abonner à l'API "Légifrance"
4. Récupérer le `client_id` et `client_secret`

## Configuration de Claude Desktop

### Configuration complète

Ajouter dans le fichier de configuration de Claude Desktop :

- **macOS** : `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows** : `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux** : `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "judilibre": {
      "command": "python",
      "args": ["/chemin/absolu/vers/mcp-magistrat-civil/servers/judilibre_mcp_server.py"],
      "env": {
        "JUDILIBRE_API_KEY": "votre_cle_api"
      }
    },
    "legifrance": {
      "command": "python",
      "args": ["/chemin/absolu/vers/mcp-magistrat-civil/servers/legifrance_mcp_server.py"],
      "env": {
        "PISTE_CLIENT_ID": "votre_client_id",
        "PISTE_CLIENT_SECRET": "votre_client_secret"
      }
    }
  }
}
```


## Intégration de la compétence Raisonnement Juridique

La compétence `raisonnement-juridique` guide Claude pour analyser des dossiers civils comme un magistrat français, en appliquant la méthodologie du syllogisme juridique.

1. Créer un fichier .zip du contenu de `skills/raisonnement-juridique/`
2. Importer la compétence dans l'onglet Capacités des paramètres de Claude


## Outils MCP disponibles

### Judilibre (jurisprudence)

| Outil | Description |
|-------|-------------|
| `judilibre_search` | Rechercher des décisions par mots-clés, chambre, date, publication |
| `judilibre_get_decision` | Récupérer le texte intégral d'une décision par son ID |
| `judilibre_get_taxonomy` | Obtenir les listes de référence (chambres, solutions, formations, publications) |
| `judilibre_get_stats` | Statistiques sur la base de données |

### Légifrance (textes légaux)

| Outil | Description |
|-------|-------------|
| `rechercher_code` | Rechercher dans les codes (Code civil, Code du travail...) |
| `rechercher_dans_texte_legal` | Rechercher dans les lois et décrets |
| `recherche_journal_officiel` | Rechercher dans le JORF |
| `recuperer_article` | Récupérer le texte intégral d'un article par son ID LEGIARTI |

## Exemple d'utilisation

### Prompt

```
Utilise la compétence raisonnement-juridique pour traiter le sujet suivant : 
Le caractère utile des diligences interruptives de péremption au sens du code de procédure civile.
```

```
Utilise la capacité raisonnement juridique pour traiter le sujet suivant : 
Quelle est la portée de la suspension des droits de visite et d'hébergement d'un enfant qui résulte d'une mesure de sûreté ? Cette suspension est elle uniquement applicable en cas de décision antérieure du juge aux affaires familiales ou s'applique t elle aussi en l'absence de toute décision du JAF. 
Question complémentaire à cette recherche: la source des droits de visite et d'hébergement est elle l'autorité parentale elle-même ?
```


## Remerciements

- [Cour de cassation](https://www.courdecassation.fr/) pour l'API Judilibre
- [DILA](https://www.dila.premier-ministre.gouv.fr/) pour l'API Légifrance
- [École nationale de la magistrature](https://www.enm.justice.fr/) pour les fiches méthodologiques

## Licence

MIT License - voir [LICENSE](LICENSE)

## Auteur

Amaury Fouret

---

*Ce projet n'est pas une publication officielle de la Cour de cassation. Il s'agit d'un outil personnel destiné à faciliter l'accès aux ressources juridiques françaises via Claude.*
