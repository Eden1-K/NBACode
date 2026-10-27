"""Team metadata and preseason priors for the 2026-27 NBA season.

PRESEASON_WINS are the consensus sportsbook over/under win totals at tip-off
(source: Hoops Rumors 2026-27 over/under recap, Oct 2026). They seed each
team's rating; real results take over as the season goes on.
"""

SEASON_START = "2026-10-20"   # opening night (US date)
SEASON_END = "2027-04-11"     # last day of the regular season (US date)
GAMES_PER_TEAM = 82

# ESPN abbreviation -> (display name, conference)
TEAMS = {
    "ATL": ("Atlanta Hawks", "East"),
    "BOS": ("Boston Celtics", "East"),
    "BKN": ("Brooklyn Nets", "East"),
    "CHA": ("Charlotte Hornets", "East"),
    "CHI": ("Chicago Bulls", "East"),
    "CLE": ("Cleveland Cavaliers", "East"),
    "DET": ("Detroit Pistons", "East"),
    "IND": ("Indiana Pacers", "East"),
    "MIA": ("Miami Heat", "East"),
    "MIL": ("Milwaukee Bucks", "East"),
    "NY": ("New York Knicks", "East"),
    "ORL": ("Orlando Magic", "East"),
    "PHI": ("Philadelphia 76ers", "East"),
    "TOR": ("Toronto Raptors", "East"),
    "WSH": ("Washington Wizards", "East"),
    "DAL": ("Dallas Mavericks", "West"),
    "DEN": ("Denver Nuggets", "West"),
    "GS": ("Golden State Warriors", "West"),
    "HOU": ("Houston Rockets", "West"),
    "LAC": ("LA Clippers", "West"),
    "LAL": ("Los Angeles Lakers", "West"),
    "MEM": ("Memphis Grizzlies", "West"),
    "MIN": ("Minnesota Timberwolves", "West"),
    "NO": ("New Orleans Pelicans", "West"),
    "OKC": ("Oklahoma City Thunder", "West"),
    "PHX": ("Phoenix Suns", "West"),
    "POR": ("Portland Trail Blazers", "West"),
    "SA": ("San Antonio Spurs", "West"),
    "SAC": ("Sacramento Kings", "West"),
    "UTAH": ("Utah Jazz", "West"),
}

PRESEASON_WINS = {
    "NY": 52.5, "BOS": 51.5, "PHI": 50.5, "TOR": 46.5, "BKN": 24.5,
    "DET": 49.5, "CLE": 48.5, "IND": 44.5, "CHI": 29.5, "MIL": 25.5,
    "MIA": 46.5, "ORL": 44.5, "ATL": 44.5, "CHA": 38.5, "WSH": 34.5,
    "OKC": 62.5, "DEN": 49.5, "MIN": 48.5, "POR": 41.5, "UTAH": 38.5,
    "LAL": 46.5, "PHX": 40.5, "GS": 39.5, "LAC": 30.5, "SAC": 20.5,
    "SA": 60.5, "HOU": 48.5, "DAL": 34.5, "MEM": 29.5, "NO": 28.5,
}

ABBRS = sorted(TEAMS)
