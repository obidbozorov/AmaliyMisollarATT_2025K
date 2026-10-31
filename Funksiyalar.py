# def narx(bazaviy_narxi, chegirma):
#     Yakuniy_narxi=bazaviy_narxi*(100-chegirma)/100
#     return Yakuniy_narxi
# Olma_Narxi=25000
# Olma_Uchun_Chegirma=5
# Olma_Yakuniy_Narxi=narx(Olma_Narxi,Olma_Uchun_Chegirma)
# print("Olma narxi:",Olma_Yakuniy_Narxi)
# def Narx(bazaviy_narxi, chegirma=0):
#     Yakuniy_narxi=bazaviy_narxi*(100-chegirma)/100
#     return Yakuniy_narxi
# Shokolad_Narxi=15000
# SHokolad_Uchun_MegaChegirma=20
# print("Shokolad narxi:",
#       Narx(bazaviy_narxi=Shokolad_Narxi, 
#            chegirma=SHokolad_Uchun_MegaChegirma))
def BalBaho(bal):
    if bal>100 or bal<0:
        return "Bunday bal mavjud emas"
    if bal>=90:
        return 5
    elif bal>=70:
        return 4
    elif bal>=60:
        return 3
    return 2
print("Balni kiriting: ")
baho=int(input())
print("Sizning bahoiz:",BalBaho(baho))