#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur MCP pour l'accès à Légifrance via API PISTE
---------------------------------------------------
Facilite l'accès aux ressources juridiques françaises via l'API Légifrance
en utilisant le protocole Model Context Protocol (MCP).

API: https://api.piste.gouv.fr/dila/legifrance/lf-engine-app
Documentation: https://www.legifrance.gouv.fr/

Auteur: Amaury Fouret
Date: Novembre 2025
"""

import os
import json
import logging
import asyncio
from typing import Any, Dict, Optional, List, Sequence
from functools import wraps
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legifrance_mcp")

# Chargement des variables d'environnement
load_dotenv()

# Constantes et configuration
CLIENT_ID = os.getenv('PISTE_CLIENT_ID')
CLIENT_SECRET = os.getenv('PISTE_CLIENT_SECRET')
OAUTH_URL = os.getenv('PISTE_OAUTH_URL', 'https://oauth.piste.gouv.fr/api/oauth/token')
BASE_URL = os.getenv('PISTE_BASE_URL', 'https://api.piste.gouv.fr/dila/legifrance/lf-engine-app')

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("Les variables PISTE_CLIENT_ID et PISTE_CLIENT_SECRET doivent être définies")

# Variables pour le cache du token OAuth
_oauth_token = None
_token_expiry = None

# Création du serveur MCP
server = Server("Serveur MCP Legifrance")

# ============================================================================
# GESTION OAUTH 2.0
# ============================================================================

def get_oauth_token() -> str:
    """
    Obtient ou renouvelle le token OAuth 2.0 pour l'API PISTE.
    Utilise un cache pour éviter de redemander un token à chaque requête.
    
    Returns:
        str: Token d'accès OAuth
    """
    global _oauth_token, _token_expiry
    
    # Vérifier si le token en cache est encore valide
    if _oauth_token and _token_expiry and datetime.now() < _token_expiry:
        return _oauth_token
    
    try:
        logger.info("Demande d'un nouveau token OAuth 2.0...")
        
        response = requests.post(
            OAUTH_URL,
            data={
                'grant_type': 'client_credentials',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'scope': 'openid'
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30
        )
        
        response.raise_for_status()
        token_data = response.json()
        
        _oauth_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 3600)
        # Renouveler 5 minutes avant l'expiration pour plus de sécurité
        _token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
        
        logger.info(f"Token OAuth obtenu avec succès (expire dans {expires_in}s)")
        return _oauth_token
        
    except Exception as e:
        logger.error(f"Erreur lors de l'obtention du token OAuth: {str(e)}")
        raise


# ============================================================================
# UTILITAIRES
# ============================================================================

def clean_dict(d: dict) -> dict:
    """
    Supprime les clés dont la valeur est None pour optimiser les requêtes API.
    
    Args:
        d (dict): Dictionnaire à nettoyer
        
    Returns:
        dict: Dictionnaire sans les valeurs None
    """
    return {k: v for k, v in d.items() if v is not None}


def rate_limit(calls: int, period: float):
    """
    Décorateur pour limiter le nombre d'appels API dans une période donnée.
    
    Args:
        calls (int): Nombre maximum d'appels autorisés
        period (float): Période en secondes
    """
    def decorator(func):
        last_reset = datetime.now()
        calls_made = 0

        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal last_reset, calls_made
            now = datetime.now()

            if (now - last_reset).total_seconds() > period:
                calls_made = 0
                last_reset = now

            if calls_made >= calls:
                wait_time = period - (now - last_reset).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    last_reset = datetime.now()
                    calls_made = 0

            calls_made += 1
            return await func(*args, **kwargs)
        return wrapper
    return decorator


async def make_api_request(endpoint: str, data: Dict) -> Dict:
    """
    Fonction générique pour effectuer des requêtes API POST avec gestion d'erreurs.
    
    Args:
        endpoint (str): Point de terminaison de l'API (ex: '/search', '/consult/code')
        data (Dict): Corps de la requête JSON
    
    Returns:
        Dict: Résultat de la requête ou message d'erreur
    """
    try:
        # Obtenir le token OAuth
        token = get_oauth_token()
        
        url = f"{BASE_URL}{endpoint}"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        clean_data = clean_dict(data)
        
        logger.info(f"Requête POST vers {endpoint}")
        logger.info(f"Corps de la requête: {json.dumps(clean_data, ensure_ascii=False, indent=2)}")
        
        res = requests.post(
            url,
            headers=headers,
            json=clean_data,
            timeout=30
        )
        
        content_type = res.headers.get("Content-Type", "")
        response_body = res.text
        
        if res.ok:
            try:
                result = res.json()
                logger.info(f"Succès: {len(json.dumps(result))} caractères reçus")
                return result
            except requests.exceptions.JSONDecodeError:
                logger.warning("Réponse non-JSON reçue")
                return {"text": response_body}
        
        # Gestion des erreurs HTTP
        if res.status_code == 400:
            return {"error": "Requête invalide. Vérifiez les paramètres."}
        elif res.status_code == 401:
            return {"error": "Authentification échouée. Vérifiez vos credentials PISTE."}
        elif res.status_code == 403:
            return {"error": "Accès refusé. Permissions insuffisantes."}
        elif res.status_code == 404:
            return {"error": "Ressource non trouvée."}
        elif res.status_code == 429:
            return {"error": "Limite de requêtes dépassée. Attendez quelques instants."}
        elif res.status_code == 500:
            logger.error(f"Erreur 500 du serveur. Corps de la réponse: {response_body[:500]}")
            return {"error": f"Erreur serveur de l'API Légifrance. Détail: {response_body[:200]}"}
        else:
            return {"error": f"Erreur HTTP {res.status_code}: {response_body[:200]}"}
            
    except requests.exceptions.Timeout:
        logger.error("Timeout de la requête API")
        return {"error": "La requête a pris trop de temps. Réessayez."}
        
    except requests.exceptions.RequestException as e:
        logger.error("Erreur de connexion à l'API", exc_info=True)
        return {"error": f"Erreur de connexion: {str(e)}"}
        
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}", exc_info=True)
        return {"error": f"Erreur inattendue: {str(e)}"}


def build_search_criteria(
    search: str,
    champ: str = "ALL",
    type_recherche: str = "TOUS_LES_MOTS_DANS_UN_CHAMP",
    operator: str = "ET"
) -> Dict:
    """
    Construit un critère de recherche pour l'API Légifrance.
    
    Args:
        search: Termes de recherche
        champ: Champ de recherche (ALL, TITLE, NUM_ARTICLE, etc.)
        type_recherche: Type de recherche (TOUS_LES_MOTS_DANS_UN_CHAMP, EXACTE, etc.)
        operator: Opérateur logique (ET, OU)
    
    Returns:
        Dict: Structure de critères pour l'API
    """
    return {
        "recherche": {
            "champs": [
                {
                    "typeChamp": champ,
                    "criteres": [
                        {
                            "typeRecherche": type_recherche,
                            "valeur": search,
                            "operateur": operator
                        }
                    ]
                }
            ],
            "pageSize": 10,
            "pageNumber": 1
        }
    }


def format_article_response(article_data: Dict) -> str:
    """
    Formate la réponse de l'API getArticle en texte lisible avec métadonnées.
    
    Args:
        article_data: Données brutes de l'article retournées par l'API
        
    Returns:
        str: Texte formaté avec le contenu et les métadonnées de l'article
    """
    if "error" in article_data:
        return f"❌ Erreur: {article_data['error']}"
    
    # Extraire l'article (peut être dans 'article' ou directement à la racine)
    article = article_data.get("article", article_data)
    
    # Construire le formatage
    lines = ["# 📜 Article de loi - Légifrance\n"]
    
    # Identifiants
    article_id = article.get("id", "N/A")
    cid = article.get("cid", "N/A")
    lines.append(f"**ID technique**: `{article_id}`")
    lines.append(f"**CID**: `{cid}`")
    
    # Numéro d'article
    num = article.get("num", article.get("numero", ""))
    if num:
        lines.append(f"**Numéro**: {num}")
    
    # Titre/Intitulé
    titre = article.get("titre", article.get("intitule", ""))
    if titre:
        lines.append(f"**Titre**: {titre}")
    
    # État de l'article
    etat = article.get("etat", article.get("articleVersions", [{}])[0].get("etat", "") if article.get("articleVersions") else "")
    if etat:
        etat_labels = {
            "VIGUEUR": "✅ En vigueur",
            "ABROGE": "❌ Abrogé",
            "MODIFIE": "🔄 Modifié",
            "VIGUEUR_DIFF": "⏳ En vigueur différée",
            "PERIME": "⚠️ Périmé"
        }
        lines.append(f"**État**: {etat_labels.get(etat, etat)}")
    
    # Dates
    date_debut = article.get("dateDebut", article.get("dateDebutVersion", ""))
    date_fin = article.get("dateFin", article.get("dateFinVersion", ""))
    if date_debut:
        lines.append(f"**Date de début**: {date_debut}")
    if date_fin:
        lines.append(f"**Date de fin**: {date_fin}")
    
    # Texte de référence (pour les articles de code)
    texte_ref = article.get("texteRef", "")
    if texte_ref:
        lines.append(f"**Texte de référence**: {texte_ref}")
    
    # Nature du texte
    nature = article.get("nature", "")
    if nature:
        lines.append(f"**Nature**: {nature}")
    
    # Lien Légifrance
    lien_legifrance = f"https://www.legifrance.gouv.fr/codes/article_lc/{article_id}"
    lines.append(f"\n**🔗 Lien Légifrance**: {lien_legifrance}")
    
    # Contenu de l'article
    lines.append("\n---\n")
    lines.append("## Texte de l'article\n")
    
    # Le texte peut être dans différents champs selon le type de réponse
    texte = article.get("texte", "")
    if not texte:
        texte = article.get("texteHtml", "")
    if not texte:
        # Chercher dans les versions
        versions = article.get("articleVersions", [])
        if versions:
            texte = versions[0].get("texte", versions[0].get("texteHtml", ""))
    if not texte:
        texte = article.get("content", article.get("contenu", ""))
    
    if texte:
        # Nettoyer le HTML basique si présent
        import re
        texte_clean = re.sub(r'<[^>]+>', '', texte)
        texte_clean = texte_clean.replace('&nbsp;', ' ').replace('&amp;', '&')
        texte_clean = texte_clean.replace('&lt;', '<').replace('&gt;', '>')
        texte_clean = texte_clean.replace('&quot;', '"').replace('&#39;', "'")
        lines.append(texte_clean.strip())
    else:
        lines.append("*Texte non disponible dans la réponse API*")
    
    # Notes et observations
    nota = article.get("nota", article.get("notaHtml", ""))
    if nota:
        lines.append("\n---\n")
        lines.append("## Nota\n")
        nota_clean = nota.replace('<p>', '').replace('</p>', '\n')
        import re
        nota_clean = re.sub(r'<[^>]+>', '', nota_clean)
        lines.append(nota_clean.strip())
    
    # Liens (articles cités, etc.)
    liens = article.get("liens", article.get("liensArticle", []))
    if liens:
        lines.append("\n---\n")
        lines.append("## Références\n")
        for lien in liens[:10]:  # Limiter à 10 liens
            type_lien = lien.get("typeLien", lien.get("type", ""))
            cible = lien.get("idCible", lien.get("cible", ""))
            texte_lien = lien.get("texteCible", lien.get("texte", ""))
            if texte_lien:
                lines.append(f"- {type_lien}: {texte_lien} (`{cible}`)")
            elif cible:
                lines.append(f"- {type_lien}: `{cible}`")
    
    return "\n".join(lines)


# ============================================================================
# DONNÉES DE RÉFÉRENCE
# ============================================================================

CODES_JURIDIQUES = {
    "Code civil": "CC",
    "Code de procédure civile": "CPC",
    "Code de commerce": "CCOM",
    "Code pénal": "CPD",
    "Code des communes": "CDC",
    "Code de l'urbanisme": "CDU",
    "Code de déontologie des architectes": "CDDDDA",
    "Code de justice administrative": "CDJA",
    "Code de justice militaire (nouveau)": "CDJM",
    "Code de l'action sociale et des familles": "CDSEDF",
    "Code de l'énergie": "CD",
    "Code de l'entrée et du séjour des étrangers et du droit d'asile": "CDEDSDEEDD",
    "Code de l'expropriation pour cause d'utilité publique": "CDPCP",
    "Code de l'organisation judiciaire": "CDJ",
    "Code de la commande publique": "CDLCP",
    "Code de la consommation": "CDLC",
    "Code de la construction et de l'habitation": "CDLCED",
    "Code de la défense": "CDLD",
    "Code de la famille et de l'aide sociale": "CDLFEDS",
    "Code de la justice pénale des mineurs": "CDLJPDM",
    "Code de la Légion d'honneur, de la Médaille militaire et de l'ordre national du Mérite": "CDLLDLMMEDNDM",
    "Code de la mutualité": "CDLM",
    "Code de la propriété intellectuelle": "CDLPI",
    "Code de la route": "CDLR",
    "Code de la santé publique": "CDLSP",
    "Code de la sécurité intérieure": "CDLSI",
    "Code de la sécurité sociale": "CDLSS",
    "Code de la voirie routière": "CDLVR",
    "Code des procédures civiles d'exécution": "CDPC",
    "Code de procédure pénale": "CDPP",
    "Code des assurances": "CDA",
    "Code des communes de la Nouvelle-Calédonie": "CDCDL",
    "Code des douanes": "CDD",
    "Code des douanes de Mayotte": "CDDDM",
    "Code des impositions sur les biens et services": "CDISLBES",
    "Code des instruments monétaires et des médailles": "CDIMEDM",
    "Code des juridictions financières": "CDJF",
    "Code des pensions civiles et militaires de retraite": "CDPCEMDR",
    "Code des pensions de retraite des marins français du commerce, de pêche ou de plaisance": "CDPDRDMFDDPODP",
    "Code des pensions militaires d'invalidité et des victimes de guerre": "CDPMEDVDG",
    "Code des ports maritimes": "CDPM",
    "Code des postes et des communications électroniques": "CDPEDCE",
    "Code des relations entre le public et l'administration": "CDRELPE",
    "Code du travail": "CDT",
    "Code disciplinaire et pénal de la marine marchande": "CDEPDLMM",
    "Code du cinéma et de l'image animée": "CDCEDA",
    "Code du domaine de l'Etat": "CDDD",
    "Code du domaine de l'Etat et des collectivités publiques applicable à la collectivité territoriale de Mayotte": "CDDDEDCPAALCTDM",
    "Code du domaine public fluvial et de la navigation intérieure": "CDDPFEDLNI",
    "Code du patrimoine": "CDP",
    "Code du service national": "CDSN",
    "Code du sport": "CDS",
    "Code du travail maritime": "CDTM",
    "Code forestier (nouveau)": "CF",
    "Code général de la fonction publique": "CGDLFP",
    "Code général de la propriété des personnes publiques": "CGDLPDPP",
    "Code général des collectivités territoriales": "CGDCT",
    "Code général des impôts": "CGDI",
    "Code général des impôts, annexe IV": "CGDAI",
    "Code minier (nouveau)": "CM",
    "Code monétaire et financier": "CMEF",
    "Code pénitentiaire": "CP",
    "Code rural (ancien)": "CR",
    "Code rural et de la pêche maritime": "CREDLPM",
    "Code électoral": "CE",
    "Livre des procédures fiscales": "LDPF"
}

EMETTEURS_JORF = [
    "MINISTERE_JUSTICE",
    "MINISTERE_INTERIEUR", 
    "MINISTERE_ECONOMIE_FINANCES",
    "MINISTERE_TRAVAIL",
    "MINISTERE_EDUCATION_NATIONALE",
    "MINISTERE_SANTE",
    "MINISTERE_CULTURE",
    "MINISTERE_DEFENSE",
    "PREMIER_MINISTRE",
    "PRESIDENCE_REPUBLIQUE"
]

NATURES_TEXTES_JORF = [
    "LOI",
    "ORDONNANCE",
    "DECRET",
    "ARRETE",
    "CIRCULAIRE",
    "DECISION",
    "AVIS"
]


# ============================================================================
# DÉFINITION DES OUTILS MCP
# ============================================================================

@server.list_tools()
async def list_tools() -> List[Tool]:
    """Liste tous les outils disponibles dans ce serveur MCP."""
    return [
        Tool(
            name="lister_codes_juridiques",
            description="Liste tous les codes juridiques disponibles sur Legifrance.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="lister_emetteurs_jorf",
            description="Liste tous les émetteurs/autorités disponibles pour les recherches JORF.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="lister_natures_textes_jorf",
            description="Liste toutes les natures de textes disponibles pour les recherches JORF.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="recuperer_article",
            description="""
Récupère le texte intégral et toutes les métadonnées d'un article de loi par son identifiant technique.

C'est l'outil à utiliser après avoir identifié un article via rechercher_code ou rechercher_dans_texte_legal
pour obtenir le texte complet et exact de l'article, indispensable pour la citation dans un raisonnement juridique.

Args:
    article_id: Identifiant technique de l'article (format LEGIARTI + 18 chiffres, ex: "LEGIARTI000038312684")

Returns:
    - Texte intégral de l'article
    - Métadonnées: numéro, titre, état (en vigueur/abrogé), dates de début/fin
    - Références: texte de rattachement, liens vers autres articles
    - Lien officiel Légifrance

Workflow recommandé:
    1. rechercher_code("victimes terrorisme", "Code des assurances") → obtenir l'ID
    2. recuperer_article("LEGIARTI000038312684") → obtenir le texte complet

Examples:
    - recuperer_article("LEGIARTI000038312684")  # Article L. 126-1 Code des assurances
    - recuperer_article("LEGIARTI000006419320")  # Article 1240 Code civil

Note:
    L'identifiant LEGIARTI se trouve dans les résultats de rechercher_code ou rechercher_dans_texte_legal,
    généralement dans le champ 'id' ou 'articleId' des résultats.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "string",
                        "description": "Identifiant technique de l'article (format LEGIARTI000...)"
                    }
                },
                "required": ["article_id"]
            }
        ),
        Tool(
            name="rechercher_code",
            description="""
Recherche des articles juridiques dans les codes de loi français.

Args:
    search: Termes de recherche (ex: "contrat de travail", "légitime défense")
    code_name: Nom complet du code juridique (ex: "Code civil", "Code du travail", "Code pénal")
    champ: Champ dans lequel rechercher (\"ALL\", \"TITLE\", \"TABLE\", \"NUM_ARTICLE\", \"ARTICLE\")
    type_recherche: Type de recherche (\"TOUS_LES_MOTS_DANS_UN_CHAMP\", \"EXACTE\", \"UN_DES_MOT\")
    sort: Tri des résultats (\"PERTINENCE\", \"DATE_DESC\", \"DATE_ASC\")
    max_results: Nombre maximum de résultats (défaut: 10, maximum: 100)

Returns:
    Liste de résultats avec les identifiants d'articles (LEGIARTI) pour utilisation avec recuperer_article

Examples:
    - rechercher_code(\"pacte civil de solidarité\", \"Code civil\")
    - rechercher_code(\"légitime défense\", \"Code pénal\")

Note:
    Utilisez 'lister_codes_juridiques' pour voir tous les codes disponibles.
    Après identification d'un article pertinent, utilisez 'recuperer_article' pour obtenir le texte complet.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "code_name": {"type": "string"},
                    "search": {"type": "string"},
                    "champ": {"type": "string", "default": "ALL"},
                    "type_recherche": {"type": "string", "default": "TOUS_LES_MOTS_DANS_UN_CHAMP"},
                    "sort": {"type": "string", "default": "PERTINENCE"},
                    "max_results": {"type": "integer", "default": 10}
                },
                "required": ["code_name", "search"]
            }
        ),
        Tool(
            name="rechercher_dans_texte_legal",
            description="""
Recherche dans les textes légaux historiques.
Il faut impérativement citer le contenu trouvé avec le lien officiel fourni par legifrance.

Args:
    search: Mots-clés de recherche ou numéro d'article
    text_id: Le numéro du texte (format AAAA-NUMERO) (optionnel)
    champ: Champ de recherche (\"ALL\", \"TITLE\", \"TABLE\", \"NUM_ARTICLE\", \"ARTICLE\")
    sort: Tri des résultats (\"PERTINENCE\", \"PUBLICATION_DATE_DESC\", \"PUBLICATION_DATE_ASC\")
    type_recherche: Type de recherche (\"TOUS_LES_MOTS_DANS_UN_CHAMP\", \"EXACTE\", \"UN_DES_MOT\")
    max_results: Nombre de résultats (défaut: 10, maximum: 100)

Returns:
    Résultats formatés avec identifiants pour utilisation avec recuperer_article

Examples:
    - Article 7 de la loi 78-17: rechercher_dans_texte_legal(\"7\", text_id=\"78-17\", champ=\"NUM_ARTICLE\")
    - Signature électronique: rechercher_dans_texte_legal(\"signature électronique validité\")
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "text_id": {"type": "string", "default": ""},
                    "champ": {"type": "string", "default": "ALL"},
                    "sort": {"type": "string", "default": "PERTINENCE"},
                    "type_recherche": {"type": "string", "default": "TOUS_LES_MOTS_DANS_UN_CHAMP"},
                    "max_results": {"type": "integer", "default": 10}
                },
                "required": ["search"]
            }
        ),
        Tool(
            name="recherche_journal_officiel",
            description="""
Recherche dans le Journal Officiel français.

Args:
    search: Mots-clés à rechercher (ex: "nomination culture")
    champ: Champ de recherche (\"ALL\", \"TITLE\", \"TABLE\", \"NOR\", etc.)
    type_recherche: Type de recherche (\"TOUS_LES_MOTS_DANS_UN_CHAMP\", \"EXACT\", \"UN_DES_MOT\")
    sort: Tri (\"PERTINENCE\", \"SIGNATURE_DATE_DESC\", etc.)
    date_publication: Date [date_debut, date_fin] format YYYY-MM-DD
    ministeres: Liste des ministères (optionnel)
    emetteurs: Liste des émetteurs/autorités
    text_types: Types de textes (LOI, DECRET, ARRETE, etc.)
    max_results: Nombre maximum de résultats (défaut: 5, maximum: 100)

Returns:
    Résultats formatés

Examples:
    - recherche_journal_officiel(\"nomination cinéma\")
    - recherche_journal_officiel(\"nomination\", ministeres=[\"MINISTERE_CULTURE\"], text_types=[\"ARRETE\"])
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "champ": {"type": "string", "default": "ALL"},
                    "type_recherche": {"type": "string", "default": "TOUS_LES_MOTS_DANS_UN_CHAMP"},
                    "sort": {"type": "string", "default": "PERTINENCE"},
                    "date_publication": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": None
                    },
                    "ministeres": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": None
                    },
                    "emetteurs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": None
                    },
                    "text_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": None
                    },
                    "max_results": {"type": "integer", "default": 5}
                },
                "required": ["search"]
            }
        )
    ]


# ============================================================================
# GESTIONNAIRE D'APPELS D'OUTILS
# ============================================================================

@server.call_tool()
@rate_limit(calls=5, period=1.0)
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    """
    Gère les appels aux outils Légifrance.
    
    Args:
        name (str): Nom de l'outil à appeler
        arguments (Any): Arguments à passer à l'outil
    
    Returns:
        Sequence[TextContent]: Résultat de l'appel
    """
    try:
        logger.info(f"Appel de l'outil: {name}")
        
        # Outils de listing
        if name == "lister_codes_juridiques":
            codes_list = "\n".join([f"- {nom}" for nom in sorted(CODES_JURIDIQUES.keys())])
            result_text = f"📚 **Codes juridiques disponibles:**\n\n{codes_list}"
            return [TextContent(type="text", text=result_text)]
        
        elif name == "lister_emetteurs_jorf":
            emetteurs_list = "\n".join([f"- {e}" for e in sorted(EMETTEURS_JORF)])
            result_text = f"🏛️ **Émetteurs JORF disponibles:**\n\n{emetteurs_list}"
            return [TextContent(type="text", text=result_text)]
        
        elif name == "lister_natures_textes_jorf":
            natures_list = "\n".join([f"- {n}" for n in sorted(NATURES_TEXTES_JORF)])
            result_text = f"📋 **Natures de textes JORF disponibles:**\n\n{natures_list}"
            return [TextContent(type="text", text=result_text)]
        
        # Récupération d'un article par son ID
        elif name == "recuperer_article":
            article_id = arguments.get("article_id", "").strip()
            
            if not article_id:
                return [TextContent(
                    type="text",
                    text="❌ Erreur: L'identifiant de l'article (article_id) est requis."
                )]
            
            # Validation basique du format
            if not article_id.startswith("LEGIARTI") and not article_id.startswith("JORFARTI"):
                return [TextContent(
                    type="text",
                    text=f"⚠️ Attention: L'identifiant '{article_id}' ne semble pas être au format standard (LEGIARTI... ou JORFARTI...). Tentative de récupération quand même..."
                )]
            
            # Appel à l'API /consult/getArticle
            request_data = {
                "id": article_id
            }
            
            result = await make_api_request("/consult/getArticle", request_data)
            
            # Gestion des erreurs
            if isinstance(result, dict) and "error" in result:
                error_text = f"❌ Erreur lors de la récupération de l'article: {result['error']}"
                return [TextContent(type="text", text=error_text)]
            
            # Formatage de la réponse
            formatted_result = format_article_response(result)
            return [TextContent(type="text", text=formatted_result)]
        
        # Recherche dans les codes
        elif name == "rechercher_code":
            code_name = arguments.get("code_name")
            search = arguments.get("search")
            champ = arguments.get("champ", "ALL")
            type_recherche = arguments.get("type_recherche", "TOUS_LES_MOTS_DANS_UN_CHAMP")
            sort = arguments.get("sort", "PERTINENCE")
            max_results = arguments.get("max_results", 10)
            
            if code_name not in CODES_JURIDIQUES:
                available = ", ".join(CODES_JURIDIQUES.keys())
                return [TextContent(
                    type="text",
                    text=f"❌ Code inconnu: '{code_name}'\n\nCodes disponibles: {available}"
                )]
            
            # Construire la requête selon la structure exacte de l'API
            request_data = {
                "fond": "CODE_DATE",
                "recherche": {
                    "champs": [
                        {
                            "typeChamp": champ,
                            "criteres": [
                                {
                                    "typeRecherche": type_recherche,
                                    "valeur": search,
                                    "operateur": "ET"
                                }
                            ],
                            "operateur": "ET"
                        }
                    ],
                    "filtres": [
                        {
                            "facette": "NOM_CODE",
                            "valeurs": [code_name]
                        }
                    ],
                    "pageNumber": 1,
                    "pageSize": min(max_results, 100),
                    "operateur": "ET",
                    "sort": sort,
                    "typePagination": "ARTICLE"
                }
            }
            
            result = await make_api_request("/search", request_data)
            
        # Recherche dans les textes légaux (LODA)
        elif name == "rechercher_dans_texte_legal":
            search = arguments.get("search")
            text_id = arguments.get("text_id", "")
            champ = arguments.get("champ", "ALL")
            type_recherche = arguments.get("type_recherche", "TOUS_LES_MOTS_DANS_UN_CHAMP")
            sort = arguments.get("sort", "PERTINENCE")
            max_results = arguments.get("max_results", 10)
            
            request_data = {
                "fond": "LODA_DATE",
                "recherche": {
                    "champs": [
                        {
                            "typeChamp": champ,
                            "criteres": [
                                {
                                    "typeRecherche": type_recherche,
                                    "valeur": search,
                                    "operateur": "ET"
                                }
                            ],
                            "operateur": "ET"
                        }
                    ],
                    "pageNumber": 1,
                    "pageSize": min(max_results, 100),
                    "operateur": "ET",
                    "sort": sort,
                    "typePagination": "DEFAUT"
                }
            }
            
            # Ajouter le filtre par ID de texte si fourni
            if text_id:
                request_data["recherche"]["filtres"] = [
                    {
                        "facette": "TEXT_ID",
                        "valeurs": [text_id]
                    }
                ]
            
            result = await make_api_request("/search", request_data)
            
        # Recherche dans le Journal Officiel
        elif name == "recherche_journal_officiel":
            search = arguments.get("search")
            champ = arguments.get("champ", "ALL")
            type_recherche = arguments.get("type_recherche", "TOUS_LES_MOTS_DANS_UN_CHAMP")
            sort = arguments.get("sort", "PERTINENCE")
            max_results = arguments.get("max_results", 5)
            
            request_data = {
                "fond": "JORF",
                "recherche": {
                    "champs": [
                        {
                            "typeChamp": champ,
                            "criteres": [
                                {
                                    "typeRecherche": type_recherche,
                                    "valeur": search,
                                    "operateur": "ET"
                                }
                            ],
                            "operateur": "ET"
                        }
                    ],
                    "pageNumber": 1,
                    "pageSize": min(max_results, 100),
                    "operateur": "ET",
                    "sort": sort,
                    "typePagination": "DEFAUT"
                }
            }
            
            # Ajouter les filtres si fournis
            filtres = []
            if arguments.get("emetteurs"):
                filtres.append({
                    "facette": "EMETTEUR",
                    "valeurs": arguments["emetteurs"]
                })
            if arguments.get("text_types"):
                filtres.append({
                    "facette": "NATURE",
                    "valeurs": arguments["text_types"]
                })
            if arguments.get("date_publication"):
                dates = arguments["date_publication"]
                if len(dates) == 2:
                    filtres.append({
                        "facette": "SIGNATURE_DATE",
                        "valeurs": dates
                    })
            
            if filtres:
                request_data["recherche"]["filtres"] = filtres
            
            result = await make_api_request("/search", request_data)
            
        else:
            return [TextContent(type="text", text=f"❌ Outil inconnu: {name}")]
        
        # Gestion des erreurs
        if isinstance(result, dict) and "error" in result:
            error_text = f"❌ Erreur: {result['error']}"
            return [TextContent(type="text", text=error_text)]
        
        # Formatage du résultat
        result_text = json.dumps(result, indent=2, ensure_ascii=False)
        
        # Ajouter un rappel sur les liens officiels pour les résultats de recherche
        if "results" in result or "hits" in str(result):
            result_text += "\n\n🔗 N'oubliez pas de mentionner les liens officiels Légifrance dans votre réponse."
            result_text += "\n💡 Utilisez 'recuperer_article(article_id)' pour obtenir le texte complet d'un article identifié."
        
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        error_message = f"❌ Erreur lors de l'exécution de {name}: {str(e)}"
        logger.error(error_message, exc_info=True)
        return [TextContent(type="text", text=error_message)]


# ============================================================================
# POINT D'ENTRÉE PRINCIPAL
# ============================================================================

async def main():
    """Point d'entrée principal du serveur MCP."""
    import mcp.server.stdio
    try:
        logger.info("🚀 Démarrage du serveur MCP Légifrance...")
        logger.info(f"URL de base: {BASE_URL}")
        logger.info(f"URL OAuth: {OAUTH_URL}")
        logger.info("Authentification: OAuth 2.0 avec PISTE")
        
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    except Exception as e:
        logger.error(f"❌ Erreur fatale lors de l'exécution du serveur: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())