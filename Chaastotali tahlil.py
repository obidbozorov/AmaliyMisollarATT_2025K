# Matnlarning chastotalarini hisoblash
def chastotalarni_hisoblash(matn):
    # Har bir harfning chastotasini hisoblash uchun lug'at yaratish
    chastotalar = {}
    
    # Matndagi har bir harfni tekshirish
    for harf in matn:
        # Agar harf allaqachon lug'atda bo'lsa, uning chastotasini oshirish
        if harf in chastotalar:
            chastotalar[harf] += 1
        else:
            # Aks holda, yangi harfni lug'atga qo'shish va chastotasini 1 ga o'rnatish
            chastotalar[harf] = 1
            
    return chastotalar
# Matn joriy oynadagi matn.txt faylidan o'qiladi
with open("matn.txt", "r", encoding="utf-8") as fayl:
    matn = fayl.read()


# Chastotalarni chiqarish chastotasi kamayib borish tartibida
#Bizga chastotalar lug'ati kerak bo'ladi, shuning uchun uni tartiblaymiz. Chastotlar faqat harflar bo'yicha. Katta kichik harflar bitta hisoblansin tartiblanadi, shuning uchun lug'atni chastota bo'yicha kamayish tartibida saralaymiz. 
# Faqat harflar bo'yicha saralash uchun, lug'atni chastota bo'yicha kamayish tartibida saralaymiz. Katta va kichik harflar bir xil hisoblanadi, shuning uchun ularni kichik harfga o'tkazamiz.  
#matndan harflardan boshqalarini o'chirib yuborish uchun, faqat harflarni hisoblashimiz kerak. Shuning uchun lug'atni kichik harflarga o'tkazamiz va faqat harflarni hisoblaymiz.
matn = ''.join(filter(str.isalpha, matn)).lower()
Chastotalar = chastotalarni_hisoblash(matn)

Chastotalar = dict(sorted(Chastotalar.items(), key=lambda item: item[1], reverse=True))
for harf, chastota in Chastotalar.items():
    print(f"'{harf}': {chastota}")
print("Chastotalar lug'ati:", Chastotalar)