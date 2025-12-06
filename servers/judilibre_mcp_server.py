#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur MCP pour l'accès à Judilibre
-------------------------------------
Facilite l'accès aux décisions de justice françaises via l'API Judilibre
en utilisant le protocole Model Context Protocol (MCP).

API: https://api.piste.gouv.fr/cassation/judilibre/v1.0
Documentation: https://github.com/Cour-de-cassation/judilibre-search

Auteur: Amaury Fouret
Date: Novembre 2025
"""

import os
import json
import logging
import asyncio
from typing import Any, Dict, Optional, List, Sequence
from functools import wraps
from datetime import datetime

import requests
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("judilibre_mcp")

# Chargement des variables d'environnement
load_dotenv()

# Constantes et configuration
API_KEY = os.getenv('JUDILIBRE_API_KEY')
BASE_URL = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"

HEADERS = {
    "accept": "application/json",
    "Content-Type": "application/json"
}

# Ajouter l'API key dans les headers si elle existe
if API_KEY:
    HEADERS["KeyId"] = API_KEY
    logger.info("API Key configurée pour un accès avancé")
else:
    raise ValueError("La variable d'environnement JUDILIBRE_API_KEY doit être définie")

# Création du serveur MCP
server = Server("judilibre")

# Utilitaires
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

            # Réinitialisation du compteur si la période est écoulée
            if (now - last_reset).total_seconds() > period:
                calls_made = 0
                last_reset = now

            # Si la limite est atteinte, attendre la fin de la période
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


async def make_api_request(endpoint: str, params: Dict) -> Dict:
    """
    Fonction générique pour effectuer des requêtes API GET avec gestion d'erreurs.
    
    Args:
        endpoint (str): Point de terminaison de l'API (ex: '/search', '/decision')
        params (Dict): Paramètres de la requête
    
    Returns:
        Dict: Résultat de la requête ou message d'erreur
    """
    try:
        url = f"{BASE_URL}{endpoint}"
        
        # Nettoyer les paramètres (supprimer les None)
        clean_params = clean_dict(params)
        
        # Convertir les types pour l'API
        for key, value in list(clean_params.items()):
            if isinstance(value, bool):
                # Convertir les booléens en chaînes minuscules (true/false)
                # L'API Judilibre attend "true" et "false" en minuscules
                clean_params[key] = "true" if value else "false"
            # Les listes sont conservées telles quelles : requests les convertira
            # automatiquement en paramètres multiples (ex: chamber=mi&chamber=pl)
        
        logger.info(f"Requête GET vers {endpoint} avec paramètres: {json.dumps(clean_params, ensure_ascii=False)}")
        
        # Requête GET (pas POST comme Legifrance)
        res = requests.get(
            url,
            headers=HEADERS,
            params=clean_params,
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
            return {"error": f"Requête invalide (400). Détails: {response_body[:500]}"}
        elif res.status_code == 401:
            return {"error": "Authentification requise. Veuillez fournir une API key valide."}
        elif res.status_code == 403:
            return {"error": "Accès refusé. Permissions insuffisantes."}
        elif res.status_code == 404:
            return {"error": f"Ressource non trouvée (404). Détails: {response_body[:500]}"}
        elif res.status_code == 416:
            return {"error": "Plage de résultats invalide. Le numéro de page est probablement trop élevé."}
        elif res.status_code == 423:
            return {"error": "Accès bloqué suite à une activité suspecte. Attendez avant de réessayer."}
        elif res.status_code == 429:
            return {"error": "Limite de requêtes dépassée. Attendez quelques instants avant de réessayer."}
        elif res.status_code == 500:
            return {"error": f"Erreur serveur de l'API Judilibre (500). Détails: {response_body[:500]}"}
        else:
            return {"error": f"Erreur HTTP {res.status_code}: {response_body[:500]}"}
            
    except requests.exceptions.Timeout:
        logger.error("Timeout de la requête API")
        return {"error": "La requête a pris trop de temps. Réessayez avec moins de résultats."}
        
    except requests.exceptions.RequestException as e:
        logger.error("Erreur de connexion à l'API", exc_info=True)
        return {"error": f"Erreur de connexion à l'API: {str(e)}"}
        
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}", exc_info=True)
        return {"error": f"Erreur inattendue: {str(e)}"}


def format_decision_markdown(decision: Dict[str, Any]) -> str:
    """Formatte une décision en Markdown pour une meilleure lisibilité."""
    lines = []
    
    # En-tête
    lines.append(f"## Décision {decision.get('number', 'N/A')}")
    lines.append("")
    
    # Informations de base
    lines.append("### Informations")
    lines.append(f"- **ID**: {decision.get('id', 'N/A')}")
    lines.append(f"- **ECLI**: {decision.get('ecli', 'N/A')}")
    lines.append(f"- **Date**: {decision.get('decision_date', 'N/A')}")
    lines.append(f"- **Juridiction**: {decision.get('jurisdiction', 'N/A')}")
    lines.append(f"- **Chambre**: {decision.get('chamber', 'N/A')}")
    lines.append(f"- **Type**: {decision.get('type', 'N/A')}")
    lines.append(f"- **Solution**: {decision.get('solution', 'N/A')}")
    
    if decision.get('publication'):
        pub = decision['publication']
        pub_str = ', '.join(pub) if isinstance(pub, list) else str(pub)
        lines.append(f"- **Publication**: {pub_str}")
    
    lines.append("")
    
    # Sommaire
    if decision.get('summary'):
        lines.append("### Sommaire")
        lines.append(decision['summary'])
        lines.append("")
    
    # Thèmes
    if decision.get('themes'):
        lines.append("### Thèmes")
        for theme in decision['themes']:
            lines.append(f"- {theme}")
        lines.append("")
    
    # Extraits pertinents (pour les résultats de recherche)
    if decision.get('highlights'):
        lines.append("### Extraits pertinents")
        for field_name, excerpts in decision['highlights'].items():
            if excerpts:
                lines.append(f"**{field_name}**:")
                for excerpt in excerpts[:3]:
                    lines.append(f"> {excerpt}")
        lines.append("")
    
    # Score de pertinence
    if decision.get('score'):
        lines.append(f"*Score de pertinence: {decision['score']:.2f}*")
        lines.append("")
    
    return "\n".join(lines)


def format_search_results(data: Dict[str, Any]) -> str:
    """Formatte les résultats de recherche en Markdown."""
    lines = []
    
    lines.append("# Résultats de recherche Judilibre")
    lines.append("")
    lines.append(f"**Total**: {data.get('total', 0)} décisions")
    lines.append(f"**Page**: {data.get('page', 0) + 1}")
    lines.append(f"**Résultats par page**: {data.get('page_size', 0)}")
    lines.append(f"**Temps de recherche**: {data.get('took', 0)}ms")
    lines.append("")
    
    results = data.get('results', [])
    if not results:
        lines.append("Aucun résultat trouvé.")
        return "\n".join(lines)
    
    lines.append(f"## {len(results)} décisions trouvées")
    lines.append("")
    
    for idx, decision in enumerate(results, 1):
        lines.append(f"### {idx}. {decision.get('number', 'N/A')} - {decision.get('decision_date', 'N/A')}")
        lines.append("")
        lines.append(f"- **ID**: {decision.get('id')}")
        lines.append(f"- **Chambre**: {decision.get('chamber', 'N/A')}")
        lines.append(f"- **Solution**: {decision.get('solution', 'N/A')}")
        
        if decision.get('summary'):
            summary = decision['summary'][:200] + "..." if len(decision['summary']) > 200 else decision['summary']
            lines.append(f"- **Sommaire**: {summary}")
        
        if decision.get('score'):
            lines.append(f"- **Pertinence**: {decision['score']:.2f}")
        
        # Extraits
        if decision.get('highlights'):
            lines.append("")
            lines.append("**Extraits**:")
            for field_name, excerpts in decision['highlights'].items():
                if excerpts and excerpts[0]:
                    lines.append(f"> {excerpts[0][:200]}...")
                    break
        
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Info de pagination
    if data.get('next_page'):
        page = data.get('page', 0)
        lines.append(f"*Pour voir plus de résultats, utilisez page={page + 1}*")
    
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> List[Tool]:
    """Liste tous les outils disponibles dans ce serveur MCP."""
    return [
        Tool(
            name="judilibre_search",
            description="""
            Recherche des décisions de justice dans la base Judilibre (Cour de cassation et Cours d'appel).
            
            Paramètres principaux:
                - query: Texte de recherche (ex: "contrat de travail", "expropriation")
                - chamber: Chambre(s) (ex: ["civ1", "civ2", "soc", "crim"])
                - jurisdiction: Juridiction(s) (ex: ["cc", "ca"])
                - date_start: Date de début (format: YYYY-MM-DD)
                - date_end: Date de fin (format: YYYY-MM-DD)
                - publication: Niveau de publication (ex: ["b", "r"])
                - solution: Type de solution (ex: ["cassation", "rejet"])
                - sort: Tri ("score", "scorepub", "date")
                - order: Ordre ("asc", "desc")
                - page: Numéro de page (commence à 0)
                - page_size: Résultats par page (max 50)
                - format_markdown: true pour formater en Markdown, false pour JSON brut
                
            Exemples:
                - Recherche simple: {query="contrat de travail", page_size=10}
                - Chambre sociale: {query="licenciement", chamber=["soc"], date_start="2023-01-01"}
                - Décisions publiées: {chamber=["crim"], publication=["b"], sort="date"}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "field": {"type": "array", "items": {"type": "string"}},
                    "operator": {"type": "string", "enum": ["or", "and", "exact"]},
                    "type": {"type": "array", "items": {"type": "string"}},
                    "theme": {"type": "array", "items": {"type": "string"}},
                    "chamber": {"type": "array", "items": {"type": "string"}},
                    "formation": {"type": "array", "items": {"type": "string"}},
                    "jurisdiction": {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "array", "items": {"type": "string"}},
                    "publication": {"type": "array", "items": {"type": "string"}},
                    "solution": {"type": "array", "items": {"type": "string"}},
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "sort": {"type": "string", "enum": ["score", "scorepub", "date"]},
                    "order": {"type": "string", "enum": ["asc", "desc"]},
                    "page": {"type": "integer", "minimum": 0},
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 50},
                    "particular_interest": {"type": "boolean"},
                    "resolve_references": {"type": "boolean"},
                    "format_markdown": {"type": "boolean"}
                }
            }
        ),
        Tool(
            name="judilibre_get_decision",
            description="""
            Récupère le contenu intégral d'une décision de justice par son ID.
            
            Paramètres:
                - id: Identifiant unique de la décision (obtenu via la recherche)
                - resolve_references: true pour avoir les noms complets au lieu des codes
                - highlight_query: Termes à surligner dans le texte
                - format_markdown: true pour formater en Markdown
                
            Retourne le texte complet, les métadonnées, le sommaire, les thèmes, etc.
            
            Exemples:
                - {id="5fca7d162a251e6bf9c78514"}
                - {id="abc123", resolve_references=true, format_markdown=true}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "resolve_references": {"type": "boolean"},
                    "query": {"type": "string"},
                    "operator": {"type": "string", "enum": ["or", "and", "exact"]},
                    "format_markdown": {"type": "boolean"}
                },
                "required": ["id"]
            }
        ),
        Tool(
            name="judilibre_get_taxonomy",
            description="""
            Récupère les listes de référence (taxonomies) utilisées par l'API.
            
            Catégories disponibles:
                - jurisdiction: Types de juridictions (cc, ca, tj, etc.)
                - chamber: Chambres (civ1, civ2, civ3, soc, crim, com, etc.)
                - type: Types de décisions (arret, ordonnance, qpc, etc.)
                - solution: Types de solutions (cassation, rejet, annulation, etc.)
                - publication: Niveaux de publication (b, r, l, c)
                - theme: Matières juridiques
                - field: Champs de recherche disponibles
                - formation: Types de formations
                - location: Localisations des juridictions
                
            Paramètres:
                - id: Catégorie à interroger (laisser vide pour voir toutes les catégories)
                - key: Obtenir le nom complet d'un code
                - value: Obtenir le code d'un nom
                - context_value: Contexte (ex: "ca" pour les chambres de cour d'appel)
                
            Exemples:
                - Lister toutes les catégories: {}
                - Lister les chambres: {id="chamber"}
                - Traduire un code: {id="jurisdiction", key="cc"}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "context_value": {"type": "string"}
                }
            }
        ),
        Tool(
            name="judilibre_get_stats",
            description="""
            Récupère des statistiques sur la base de données Judilibre.
            
            Paramètres:
                - keys: Dimensions d'agrégation (ex: "year,jurisdiction", "chamber,solution")
                - jurisdiction: Filtrer par type de juridiction
                - location: Filtrer par localisation
                - date_start: Date de début
                - date_end: Date de fin
                - particular_interest: Uniquement les décisions d'intérêt particulier
                
            Options pour 'keys': year, month, jurisdiction, source, location, theme, 
                                  formation, chamber, solution, type, publication
                
            Exemples:
                - Statistiques globales: {}
                - Par année: {keys="year"}
                - Par juridiction et année: {keys="jurisdiction,year"}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "keys": {"type": "string"},
                    "jurisdiction": {"type": "string"},
                    "location": {"type": "string"},
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "particular_interest": {"type": "boolean"}
                }
            }
        )
    ]


@server.call_tool()
@rate_limit(calls=10, period=1.0)  # Limite à 10 appels par seconde
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    """
    Gère les appels aux outils Judilibre.
    
    Args:
        name (str): Nom de l'outil à appeler
        arguments (Any): Arguments à passer à l'outil
    
    Returns:
        Sequence[TextContent]: Résultat de l'appel
    """
    try:
        logger.info(f"Appel de l'outil: {name}")
        
        # Extraction du paramètre de formatage
        format_markdown = arguments.pop('format_markdown', True)
        
        if name == "judilibre_search":
            # Renommer particularInterest pour l'API
            if 'particular_interest' in arguments:
                arguments['particularInterest'] = arguments.pop('particular_interest')
            
            result = await make_api_request("/search", arguments)
            
            # Formatage du résultat
            if isinstance(result, dict) and "error" not in result and format_markdown:
                formatted = format_search_results(result)
                return [TextContent(type="text", text=formatted)]
            
        elif name == "judilibre_get_decision":
            result = await make_api_request("/decision", arguments)
            
            # Formatage du résultat
            if isinstance(result, dict) and "error" not in result and format_markdown:
                formatted = format_decision_markdown(result)
                # Ajouter le texte complet si disponible
                if result.get('text'):
                    formatted += "\n\n### Texte intégral\n\n"
                    text = result['text']
                    # Limiter à 5000 caractères pour éviter de surcharger
                    if len(text) > 50000:
                        formatted += text[:50000] + "\n\n[...texte tronqué...]"
                    else:
                        formatted += text
                return [TextContent(type="text", text=formatted)]
            
        elif name == "judilibre_get_taxonomy":
            result = await make_api_request("/taxonomy", arguments)
            
        elif name == "judilibre_get_stats":
            # Renommer particularInterest pour l'API
            if 'particular_interest' in arguments:
                arguments['particularInterest'] = arguments.pop('particular_interest')
            
            result = await make_api_request("/stats", arguments)
            
        else:
            return [TextContent(type="text", text=f"Outil inconnu: {name}")]
        
        # Gestion des erreurs
        if isinstance(result, dict) and "error" in result:
            error_text = f"❌ Erreur: {result['error']}"
            return [TextContent(type="text", text=error_text)]
        
        # Retour du résultat en JSON
        result_text = json.dumps(result, indent=2, ensure_ascii=False)
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        error_message = f"❌ Erreur lors de l'exécution de {name}: {str(e)}"
        logger.error(error_message, exc_info=True)
        return [TextContent(type="text", text=error_message)]


async def main():
    """Point d'entrée principal du serveur MCP."""
    import mcp.server.stdio
    try:
        logger.info("🚀 Démarrage du serveur MCP Judilibre...")
        logger.info(f"URL de base: {BASE_URL}")
        logger.info(f"Mode: {'Authentifié' if API_KEY else 'Public'}")
        
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