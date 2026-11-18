# Ikki kishi o'rtasidagi dialog

def dialog(kishi1, kishi2, savollar):
    for savol, javob in savollar:
        print(f"{kishi1}: {savol}")
        print(f"{kishi2}: {javob}")
        print()

# Dialog savollari va javoblari
savollar = [
    ("Salom! Qandaysiz?", "Salom! Yaxshi, rahmat. O'zingiz qandaysiz?"),
    ("Men ham yaxshi, rahmat. Bugun ishlar qanday?", "Ishlar yaxshi, lekin biroz bandman."),
    ("Nima ustida ishlayapsiz?", "Yangi loyiha ustida ishlayapman."),
    ("Qaysi loyiha?", "Python dasturlash bo'yicha o'quv materiallari."),
    ("Qiziqarli! Muvaffaqiyat tilayman!", "Rahmat, katta rahmat!"),
]

print("=== Dialog boshlandi ===")
print()
dialog("Ali", "Vali", savollar)
print("=== Dialog tugadi ===")
