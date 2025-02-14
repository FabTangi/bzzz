#version V1 : y a le local capteur et le distant, on peut tester en local (sans lora), on enregistre sur eeprom un des deux capteurs v2 -> deux capteurs locaux et un distant; v3 -> corrige gros
#bug : il faut faire une pseudo-mesure avant de démarrer, bof, finalement on fait moyenne de 100 mesures, v4-> temperature et label, v5-> deux capteurs dans le distant (poids = somme des deux)
#v6-> on rajoute un capteur local aux deux distants (v5 ne marche plus) puis versions tx_rx_v1: on y met les deux, ainsi que la lecture; version tx_rx_v2 : config 4 capteurs 20kg;
#version tx_rx_v3 : on fait un cycle de mesures sur n points, b fois de suite en envoyant un numéro de trame sauvé sur EEPROM TX (on s'est aperçu qu'on perdait bcp de trames), tx_rx_v_4 : 6 capteurs
#version tx_rx_v_1.py : on passe en python,v_9 commence à marcher avec un capteur sauf HX711 mode degradé; v_10 hx711 semble marcher après exclusion des valeurs 2**n-1;
#v_11 : deux capteurs conf 120, v_12 : 6 capteurs RX et TX;
#v_13 : mauvaise précision sur v_12, on va tester la mesure par rapport à la dernière archivée sur flash TX avec un paramètre de précision;
#v_14 : on allege conf 206 ->conf 2, un cycle dure 12 secondes pour pouvoir émettre 20 000 trames avec 2600 mAh *2 (on vise 50000) , on passe au Lopy 4 (suppression du shield deepsleep et donc de deepsleep.py
#v_15 : on rajoute un chien de garde pour éviter les plantages réguliers (tous les 2/3 jours pour TX, un peu mieux pour RX), on passe tous les paramètres à config
#v_16 : on transmet le poids ou bien la valeur brute ADC, selon le choix des capteurs
#v_17 : on passe aux modes lora APB et RAW, (OTAA en test), on modifie hx711, on supprime toute écriture sur flash, on écarte valeur min et valeur max du calcul de la mesure, on mesure Tension batterie
#v_18 : on fait trois mains, un RX (70 lignes), un TX(110 lignes) et un RX_TX (250 lignes), pour réduire le temps de compilation. On passe de 3.8s à 3.5s puis 2.6s. 10% gain sur TX -> bof, bof, le RX ne sert à rien et le TX?
import pycom
import os
from hx711 import HX711
from network import LoRa
import socket
import time
import config as c
import machine
from machine import WDT
from machine import RTC
from machine import ADC
import errno
from network import WLAN
import ubinascii

def acquisitionCapteur( capteur) :
     capteur.power_up()#reveille le HX711 n°'capteur'
     time.sleep (c.delai_avant_acquisition)
     lecture_capteur = capteur.read()
     capteur.power_down()# put the ADC in sleep mode
     return lecture_capteur

def flashWriteData(trame) : #on écrit trame dans fichier data
    print ("ecriture de trame")
    ofi=open('fichier_data', 'a')
    dispo=os.getfree('/flash')# vérifie si y a de la place sur flash
    if dispo > 100:
        ofi.write(trame)
    else:
        print ("memoire saturee")
        pycom.rgbled(c.jaune_pale) #si pas de mémoire, on arrête le programme qui va rebooter à l'infini à cause du chien de garde
        time.sleep(c.timeout/1000)
    ofi.close()
    return

def temperatureLopy(GAIN,OFFSET) : #toujours pas de code fiable pour obtenir la température de l'ESP32???? le 23/9/2019
    t=GAIN+OFFSET#***********************************************************fonction bidon
    return t

def tensionBatterie():
    adc = ADC()
    batt = adc.channel(attn=c.attn, pin=c.pinBatt)# attenuation = 1, correspond à 3dB: gamme 0-1412 mV, pont diviseur (115k et 56k) sur expansion board V2.1A de 3.05, ADC 12 bits : 4096
    v=batt.value()
    if v==c.resolutionADC-1:
        v=-1
    v=int(v*c.range/c.resolutionADC*c.coeff_pont_div)#mV
    return v

#Init constantes, selon fichier config.py
configuration=c.configuration                                     #configuration   =1 on configure le RX,  configuration   =2 on configure le TX,
debug=c.debug
mode_lora=c.mode_lora                                             #mode LoRa:  RAW,  APB,  OTAA;
data_rate=c. data_rate # set the LoRaWAN data rate
nombre_point=c.nombre_point                                   #c'est le nombre d'acquisitions faites par le HX711, qui en fait une moyenne appelée mesure
label=c.label                                                                #controle expéditeur sur label, en mode RAW seulement
delimiteur=c.delimiteur                                               #delimiteur entre champs de la trame
w=c.w                                                                          #champ identification (nom de la ruche, ...)
nombre_capteurs=c.nombre_capteurs                #nombre de capteurs sur la balance TX ou RX
premier_capteur  =c.premier_capteur                 #premier_capteur  sur la balance TX ou RX

# Init HX711 module, hx.tare(c.HX_TARE), hx.set_scale(c.HX_SCALE)#cf fichier config capteur_i= HX711(DOUT,SCK)
capteur_0 = HX711(c.HX_DT_1, c.HX_SCK_1)     #capteur 20kg_i
capteur_1 = HX711(c.HX_DT_2, c.HX_SCK_2)     #capteur 20kg_i
capteur_2 = HX711(c.HX_DT_3, c.HX_SCK_3)     #capteur 20kg_i
capteur_3 = HX711(c.HX_DT_4, c.HX_SCK_4)     #capteur 20kg_i

capteurs=[capteur_0,capteur_1,capteur_2,capteur_3]
tare =c.tare                                                  # tare_i : valeur ADC sans rien sur le capteur
coeff=c.coeff                                                #coeff multiplicateur pour obtenir des grammes
sleep=c.sleep                                               #init deepsleep

temperature_distant=temperature_local=poids_en_grammes=poids_en_gr_distant_total=poids_en_gr_local_total=numero_trame=0
lecture_capteur=[0]*4
rtc = RTC()
rtc.init(c.date)       #mise à l'heure selon fichier configuration
pycom.heartbeat(False)
pycom.rgbled(c.violet)                                             # flash violet
time.sleep (c.delai_flash_mise_en_route)
pycom.rgbled(c.BLACK)
wdt = WDT(timeout=c.timeout)                                 # enable  watchgdog with a timeout of c.timeout milliseconds
print ('conf: ',configuration,  'LoRa: ', mode_lora,'debug: ',debug,'date: ',rtc.now(), 'premier_capteur: ',c.premier_capteur, 'nombre_capteurs: ',c.nombre_capteurs, 'tension_Bat',tensionBatterie())

t0=time.time()
t2=time.time()

poids_en_gr=poids_en_gr_total=moyenne=tension=trame=0
lora = LoRa(mode=LoRa.LORAWAN, region=LoRa.EU868)
if lora.has_joined() == False :
    if mode_lora== 'APB'              : #APB (on émet en mode crypté sans recevoir d'ACK de la part du récepteur qui est le RX ou la GW) ABP stands for Authentication By Personalisation.
        print("APB Mode")
        print(trame)

        lora.join(activation=LoRa.ABP, auth=(c.dev_addr,c.nwk_swkey, c.app_swkey))        # join a network using ABP (Activation By Personalization), Les clés ont été  fournies avant le joint par TTN (par ex).
        s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)        # create a LoRa socket
        s.setsockopt(socket.SOL_LORA, socket.SO_DR, data_rate)        # set the LoRaWAN data rate
        #s.setblocking(True)                # make the socket blocking

    if mode_lora== 'OTAA'              : #  OTAA (mode complet mais, le plus lent, avec échange entre TX et récepteur)

        lora.join(activation=LoRa.OTAA, auth=(c.app_eui, c.app_key), timeout=0)        # join a network using OTAA (Over the Air Activation) needing a 'handshake' procedure to exchange the keys

        while not lora.has_joined():                # wait until the module has joined the network
            time.sleep(2.5)
            print('Not yet joined...')
        s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)        # create a LoRa socket
        s.setsockopt(socket.SOL_LORA, socket.SO_DR, 5)        # set the LoRaWAN data rate
        #s.setblocking(True)        # make the socket blocking       # (waits for the data to be sent and for the 2 receive windows to expire)

while True:
    print("boucle true")
    if c.nombre_capteurs!=0 : #On va faire la mesure sur le RX ou le TX; il y a nombre_capteurs capteurs sur le TX ou RX
    #trame=[label+delimiteur]+str(t)+delimiteur+w+{delimiteur+str(lecture_capteur[i])}*nombre_capteurs+delimiteur+"\n" #; la trame RAW nécessite un "label" pour identification sans ambigüité
        adc = ADC()
        batt = adc.channel(attn=c.attn, pin=c.pinBatt)# attenuation = 1, correspond à 3dB: gamme 0-1412 mV, pont diviseur (115k et 56k) sur expansion board V2.1A de 3.05, ADC 12 bits : 4096
        pycom.rgbled(c.BLACK)
        if debug:
            pycom.rgbled(c.bleu_pale)
            time.sleep(c.delai_flash_mise_en_route)
        trame=''
        poids_en_gr=poids_en_gr_total=moyenne=tension=0
        t1=moy=[0]*nombre_point
        for i in range(premier_capteur, nombre_capteurs+premier_capteur): #on fait la mesure sur les i capteur_i de premier_capteur à premier_capteur+nombre_capteurs
            capteur=capteurs[i]
            lecture_capteur[i-premier_capteur]=n= moyenne=0
            capteur.power_up()#reveille le HX711 n°'capteur'
            time.sleep (c.delai_avant_acquisition)
            for n in range(0, nombre_point) :
                lecture_capteur[i-premier_capteur]=capteur.read()  #fait l'acquisition sur le capteur _i
                lecture_capteur[i-premier_capteur]=int( (lecture_capteur[i-premier_capteur]-tare[i])*coeff[i])#calcule le poids en grammes
                if debug:
                    print(' capteur n°', i,  '   poids ',  lecture_capteur[i-premier_capteur], end="")
                    pycom.rgbled(c.GREEN)
                    time.sleep (c.delai_avant_acquisition)
                moy[n]=int(lecture_capteur[i-premier_capteur])
                n+=1
            moy.sort()
            lecture_capteur=[0]*9
            poids_en_gr_total=0
            for n in range(1, nombre_point-1):#on élimine minimum et maximum
                lecture_capteur[i-premier_capteur]+=moy[n]
                n+=1
            lecture_capteur[i-premier_capteur]=int(lecture_capteur[i-premier_capteur]/(nombre_point-2))
            poids_en_gr_total+= lecture_capteur[i-premier_capteur]
            trame+=str( lecture_capteur[i-premier_capteur])+delimiteur
            print('trame')
            print(trame)
            capteur.power_down()# put the ADC n° i in sleep mode
            i+=1
        for n in range(0, nombre_point) :
            t1[n]=batt.value()
            if debug:
                print('tension_digits : ', t1[n], end='')
            n+=1
        t1.sort()
        tension=0
        for n in range(1, nombre_point-1):#on élimine minimum et maximum
            tension+=t1[n]
            n+=1
        tension=int(tension*c.range/c.resolutionADC*c.coeff_pont_div /(nombre_point-2))#mesure de la tension Batterie du TX en mV
        if mode_lora=='RAW' :
            trame=label+delimiteur+str(tension)+delimiteur+w+delimiteur+trame
        else:
            trame=str(tension)+delimiteur+w+delimiteur+trame
            print('trame')
            print(trame)
        if debug:
            pycom.rgbled(c.blanc)
            time.sleep(c.delai_flash_mise_en_route)
        t2=time.time()

    if configuration=='TX': # On va émettre la trame LoRa par le TX, puis endormir le TX


        tension=int(tension*c.range/c.resolutionADC*c.coeff_pont_div /(nombre_point-2))#mesure de la tension Batterie du TX en mV
        if mode_lora=='RAW' :
            trame=label+delimiteur+str(tension)+delimiteur+w+delimiteur+trame
        else:
            trame=str(tension)+delimiteur+w+delimiteur
            print('trame tension')
            print(trame)



        s.setblocking(True)        # make the socket blocking       # (waits for the data to be sent and for the 2 receive windows to expire)
        print("emission")
        time.sleep(c.delai_flash_mise_en_route)
        print(trame)
        #s.send(bytes([1, 2, 3]))
        s.send (trame) #trame
        time.sleep(c.tempo_lora_emission)
        s.setblocking(False)
        print("Socket débloquée, réception de données si besoin")
        # get any data received (if any...)
        data = s.recv(64)
        print(data)
        numero_trame+=1
        print(numero_trame)
        pycom.rgbled(c.RED)                                             # flash rouge
        time.sleep (c.delai_flash_mise_en_route)
        if debug:
            print("poids_en_gr_total", poids_en_gr_total, " tension_Batterie: ", tension, '****'," N_T: ",  numero_trame," ",  trame)
        #machine.deepsleep(c.sleep)                                     #eteint Lopy

    deltaT2=time.time()-t2 #temps écoulé depuis la dernière mesure locale
    print(deltaT2)
    wdt.feed() # feeds  watchgdog

print('FIN')
