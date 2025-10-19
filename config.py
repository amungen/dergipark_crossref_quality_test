# config.py
CROSSREF_API_TEMPLATE = (
    "https://api.crossref.org/journals/{issn}/works"
    "?select=DOI,prefix,title,publisher,type,resource,URL,ISSN,created,container-title"
    "&rows=50&sort=created&order=asc"
)

UA = "AcademicLinkTester/1.0"
TIMEOUT = 5

# Başlangıç index'i (1-based). 1: baştan başlar; ör. 2162 ise 2162'den itibaren işler.
START_INDEX = 1

# Hedef siteleri yormamak için (saniye)
POLITE_DELAY = 0.5
