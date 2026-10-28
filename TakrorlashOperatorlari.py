# for i in range(1,10,1):
#     print(i)
# for i in range(1,21,2):
#     print(i)
# for i in range(7,77):
#     print(i)
# for i in range(100):
#     print(i)
# Summa=0
# for i in range(1,101):
#     Summa+=i
# print("1 dan 100 gacha sonlar yig'indisi=",Summa)
# Suz="SALOM DUNYO"
# for i in Suz:
#     print(i)
# i=1
# while i<=10:
#     print(i)
    
# print("1 dan 10 gacha sonlar chiqarildi")
OqYaktakli=0
KukYaktakli=0
vaqt=0
while True:
    vaqt+=1
    KukYaktakli+=int(input("Kuk yaktakli bali: "))
    OqYaktakli+=int(input("Oq yaktakli bali: "))
    if vaqt<=300:
        if KukYaktakli>=100:
            print("Kuk yaktakli G'olib bo'ldi, IPPON")
            break
        if OqYaktakli>=100:
            print("Oq yaktakli G'olib bo'ldi")
            break
    else:
        KukYaktakli+=int(input("Kuk yaktakli bali: "))
        OqYaktakli+=int(input("Oq yaktakli bali: "))
        if KukYaktakli>=0:
            print("Kuk yaktakli G'olib bo'ldi")
            break
        if OqYaktakli>=0:
            print("Oq yaktakli G'olib bo'ldi")
            break
