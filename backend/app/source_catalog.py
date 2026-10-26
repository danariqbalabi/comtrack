"""Suggestions only; no automatic subscription or claims of current availability."""
WEBSITES = [
    ("OU Festival · EPIC (teruji)", "https://ou-festival.com/", None),
    ("Sorota · Business Plan 2026", "https://sorota.id/kompetisi/business-plan-2026", None),
    ("Pusbisnas", "https://www.pusbisnas.com/", "article a"),
    ("Info Lomba", "https://infolomba.id/", "a[href*='info-']"),
    ("SIM UNS · Info Lomba", "https://sim.uns.ac.id/lomba", None),
    ("INFEST · BCC", "https://www.infestbdg.com/daftar/ketentuan/bcc", None),
    ("UGP GBIC Festival", "https://gbic2026.com/lomba/ugbic-2026", None),
    ("Tarbak Unifest", "https://unifest.tbu.ac.id/", None),
    ("INSPACE ITK", "https://inspc.space/", None),
    ("Info-lomba.com (arsip; cek tanggal)", "https://www.info-lomba.com/", ".post-title a"),
]
INSTAGRAM = [
    "csrelatedcompetitions", "csrelatedcompetition", "lombabisnis", "infolomba", "info.lomba", "infolomba.id",
    "infolombamahasiswa", "lombamahasiswa", "sejutacita.id", "eventhunterindonesia", "eventhunter.id",
    "eventbanget", "eventcampus", "menanglomba", "pusbisnas", "kemahasiswaan.dikti", "puspresnas",
    "gemastik", "compfest", "arkavidia", "schematics.its", "ifest_unpad", "inspace_itk", "infest.bdg",
    "hishot.prasetiyamulya", "iibc.ugm", "managementevents", "uiinnovationwar",
]


def catalog():
    rows = [{"name": name, "kind": "website", "url": url, "links_selector": selector,
             "note": "Adapter OU Festival teruji langsung." if index == 0 else "Kandidat website; akses, struktur, dan relevansi perlu diperiksa saat pencarian."}
            for index, (name, url, selector) in enumerate(WEBSITES)]
    rows += [{"name": "@" + name, "kind": "instagram", "url": "https://www.instagram.com/" + name + "/",
              "links_selector": None, "note": "Kandidat akun; belum diverifikasi lewat provider. Username/akses dapat berubah."} for name in INSTAGRAM]
    return rows
