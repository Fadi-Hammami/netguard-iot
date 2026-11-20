/* =========================================================================
 * Station de surveillance multi-capteurs - MSP432P401R + Grove BoosterPack
 * Version finale : envoi vers l'ESP32 (J11) + debug PuTTY simultane
 * =========================================================================
 *
 * Materiel :
 *   - LaunchPad MSP-EXP432P401R + Grove BoosterPack
 *   - DHT22 (temperature/humidite)  -> J5 (Analog, utilise en GPIO)
 *   - Capteur de son                -> J6 (Analog)
 *   - Capteur de lumiere            -> J7 (Analog)
 *   - Buzzer                        -> J13 (Digital)
 *   - PIR (detecteur de mouvement)  -> J14 (Digital)
 *   - Liaison vers l'ESP32          -> J11 (Serial / UART)
 *
 * Brochage :
 *   - J5  (Analog)  -> P6.1               : signal DHT22 (protocole 1-fil)
 *   - J6  (Analog)  -> P4.0 / A13         : signal capteur de son
 *   - J7  (Analog)  -> P4.2 / A11         : signal capteur de lumiere
 *   - J13 (Digital) -> P2.7               : signal Buzzer
 *   - J14 (Digital) -> P2.4               : signal PIR
 *   - J11 (Serial)  -> P3.2 (RXD) / P3.3 (TXD)  : eUSCI_A2, vers l'ESP32
 *
 * IMPORTANT : d'apres la documentation officielle TI (MSP432P401R LaunchPad
 * User's Guide, SLAU597), le backchannel UART utilise par PuTTY est
 * eUSCI_A0 (P1.2/P1.3), et il est INDEPENDANT de l'UART expose sur le
 * connecteur 40 broches (pins 3/4), qui utilise eUSCI_A2 (P3.2/P3.3).
 * Ce sont donc deux liaisons totalement separees qui peuvent fonctionner
 * en meme temps sans aucun conflit :
 *   - eUSCI_A0 (P1.2/P1.3) -> reste branche au cable USB -> PuTTY (debug)
 *   - eUSCI_A2 (P3.2/P3.3) -> sort sur J11 -> ESP32 (UART2, GPIO16/17)
 *
 * Chaque trame JSON est envoyee sur LES DEUX UART en meme temps : ca
 * permet de garder un oeil sur PuTTY tout en etant sur que l'ESP32
 * recoit exactement la meme chose.
 *
 * ------------------------------------------------------------------------
 * MOTEUR DE REGLES ENRICHI (priorite de haut en bas) :
 *   1) Temperature >= 32C  ET  PIR actif        -> "CRITIQUE"
 *   2) PIR actif  ET  son fort (>= seuil)        -> "INTRUSION"
 *   3) PIR actif  ET  obscurite (lumiere basse)  -> "MOUVEMENT_NUIT"
 *   4) Temperature >= 32C (sans presence)        -> "ENVIRONNEMENTALE"
 *   5) PIR actif seul (rien d'autre)             -> "PRESENCE"
 *   6) Rien de particulier                       -> "AUCUNE"
 * ========================================================================= */

#include "msp.h"
#include <stdint.h>

/* ------------------------------------------------------------------- */
/*  Constantes                                                          */
/* ------------------------------------------------------------------- */
#define CPU_FREQ_HZ           12000000UL

#define DHT_PIN               0x02   /* P6.1 -> BIT1  (J5) */

#define BUZZER_PIN            0x80   /* P2.7 -> BIT7  (J13) */
#define PIR_PIN               0x10   /* P2.4 -> BIT4  (J14) */

#define NB_ECHANTILLONS_SON   200    /* fenetre de mesure du son */

#define SEUIL_TEMP_C          32.0f  /* seuil temperature (C) */
#define SEUIL_SON             300u   /* seuil amplitude sonore (0..16383) */
#define SEUIL_LUMIERE_FAIBLE  3000u  /* en dessous = obscurite (0..16383) */

/* ------------------------------------------------------------------- */
/*  1) Horloge : DCO a 12 MHz, MCLK = SMCLK = DCO                        */
/* ------------------------------------------------------------------- */
void Clock_Init12MHz(void)
{
    CS->KEY  = 0x695A;
    CS->CTL0 = 0;
    CS->CTL0 = CS_CTL0_DCORSEL_3;
    CS->CTL1 = CS_CTL1_SELA_2 | CS_CTL1_SELS_3 | CS_CTL1_SELM_3;
    CS->KEY  = 0;
}

/* ------------------------------------------------------------------- */
/*  2a) UART DEBUG (eUSCI_A0) sur P1.2 (RXD) / P1.3 (TXD) - PuTTY        */
/* ------------------------------------------------------------------- */
void UART_Debug_init(void)
{
    P1->SEL0 |=  (1 << 2) | (1 << 3);
    P1->SEL1 &= ~((1 << 2) | (1 << 3));

    EUSCI_A0->CTLW0 = 0x0001;
    EUSCI_A0->BRW   = 78;
    EUSCI_A0->MCTLW = (2 << 4) | 0x0001;
    EUSCI_A0->CTLW0 = (1 << 7);
}

void UART_Debug_sendChar(char c)
{
    while (!(EUSCI_A0->IFG & 0x0002));
    EUSCI_A0->TXBUF = c;
}

void UART_Debug_sendString(const char *str)
{
    while (*str)
    {
        UART_Debug_sendChar(*str++);
    }
}

/* ------------------------------------------------------------------- */
/*  2b) UART VERS ESP32 (eUSCI_A2) sur P3.2 (RXD) / P3.3 (TXD) - J11     */
/* ------------------------------------------------------------------- */
void UART_ESP32_init(void)
{
    P3->SEL0 |=  (1 << 2) | (1 << 3);   /* P3.2/P3.3 -> fonction UART (eUSCI_A2) */
    P3->SEL1 &= ~((1 << 2) | (1 << 3));

    EUSCI_A2->CTLW0 = 0x0001;           /* UCSWRST = 1 : module en reset */

    /* 12 000 000 Hz / (16 x 9600) = 78,125  ->  UCBRx = 78, UCBRFx = 2  */
    EUSCI_A2->BRW   = 78;
    EUSCI_A2->MCTLW = (2 << 4) | 0x0001;

    EUSCI_A2->CTLW0 = (1 << 7);         /* UCSSELx = SMCLK, UCSWRST = 0 */
}

void UART_ESP32_sendChar(char c)
{
    while (!(EUSCI_A2->IFG & 0x0002));
    EUSCI_A2->TXBUF = c;
}

void UART_ESP32_sendString(const char *str)
{
    while (*str)
    {
        UART_ESP32_sendChar(*str++);
    }
}

/* Envoie la meme chaine sur les deux UART (debug PuTTY + ESP32) */
void UART_sendString_Tout(const char *str)
{
    UART_Debug_sendString(str);
    UART_ESP32_sendString(str);
}

/* ------------------------------------------------------------------- */
/*  3) Base de temps (SysTick) pour delais en microsecondes/millisecondes*/
/* ------------------------------------------------------------------- */
void SysTick_start(void)
{
    SysTick->CTRL = 0;
    SysTick->LOAD = 0x00FFFFFF;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_ENABLE_Msk;
}

uint32_t SysTick_elapsedUs(uint32_t depart)
{
    uint32_t maintenant = SysTick->VAL;
    uint32_t ticks;

    if (depart >= maintenant)
    {
        ticks = depart - maintenant;
    }
    else
    {
        ticks = (0x00FFFFFF - maintenant) + depart;
    }
    return ticks / (CPU_FREQ_HZ / 1000000UL);
}

void delay_us(uint32_t us)
{
    uint32_t depart = SysTick->VAL;
    while (SysTick_elapsedUs(depart) < us)
    {
        /* attente active */
    }
}

void delay_ms(uint32_t ms)
{
    while (ms--)
    {
        delay_us(1000);
    }
}

/* ------------------------------------------------------------------- */
/*  4) Pilote du DHT22 sur P6.1 (J5)                                     */
/* ------------------------------------------------------------------- */
void DHT_setOutputLow(void)
{
    P6->DIR |= DHT_PIN;
    P6->OUT &= ~DHT_PIN;
}

void DHT_release(void)
{
    P6->OUT |= DHT_PIN;
    P6->DIR &= ~DHT_PIN;
    P6->REN |= DHT_PIN;
    P6->OUT |= DHT_PIN;
}

uint8_t DHT_read(void)
{
    return (P6->IN & DHT_PIN) ? 1 : 0;
}

uint8_t DHT_waitLevel(uint8_t niveau, uint32_t timeout_us)
{
    uint32_t depart = SysTick->VAL;
    while (DHT_read() != niveau)
    {
        if (SysTick_elapsedUs(depart) > timeout_us)
        {
            return 0;
        }
    }
    return 1;
}

uint8_t DHT22_read(float *temperature, float *humidite)
{
    uint8_t data[5] = {0, 0, 0, 0, 0};
    uint8_t i, j;
    uint32_t depart;

    DHT_setOutputLow();
    delay_ms(2);
    DHT_release();
    delay_us(30);

    if (!DHT_waitLevel(0, 100)) return 0;
    if (!DHT_waitLevel(1, 100)) return 0;
    if (!DHT_waitLevel(0, 100)) return 0;

    for (i = 0; i < 5; i++)
    {
        for (j = 0; j < 8; j++)
        {
            if (!DHT_waitLevel(1, 100)) return 0;

            depart = SysTick->VAL;
            if (!DHT_waitLevel(0, 150)) return 0;

            data[i] <<= 1;
            if (SysTick_elapsedUs(depart) > 40)
            {
                data[i] |= 1;
            }
        }
    }

    if (data[4] != ((data[0] + data[1] + data[2] + data[3]) & 0xFF))
    {
        return 0;
    }

    {
        uint16_t rh_brut = ((uint16_t)data[0] << 8) | data[1];
        uint16_t t_brut  = ((uint16_t)data[2] << 8) | data[3];

        *humidite = rh_brut / 10.0f;

        if (t_brut & 0x8000)
        {
            t_brut &= 0x7FFF;
            *temperature = -(t_brut / 10.0f);
        }
        else
        {
            *temperature = t_brut / 10.0f;
        }
    }

    return 1;
}

/* ------------------------------------------------------------------- */
/*  5) ADC14 : lecture generique sur un canal donne                     */
/* ------------------------------------------------------------------- */
void ADC_Init(void)
{
    /* P4.0 (A13, son) et P4.2 (A11, lumiere) en fonction analogique */
    P4->SEL0 |= 0x01 | 0x04;
    P4->SEL1 |= 0x01 | 0x04;

    ADC14->CTL0 &= ~ADC14_CTL0_ENC;
    ADC14->CTL0 = ADC14_CTL0_SHT0__16 | ADC14_CTL0_SHP | ADC14_CTL0_ON;
    ADC14->CTL1 = ADC14_CTL1_RES__14BIT;
}

uint16_t ADC_readChannel(uint8_t canal)
{
    ADC14->CTL0 &= ~ADC14_CTL0_ENC;
    ADC14->MCTL[0] = canal;
    ADC14->CTL0 |= ADC14_CTL0_ENC | ADC14_CTL0_SC;

    while (!(ADC14->IFGR0 & ADC14_IFGR0_IFG0))
    {
        /* attend la fin de la conversion */
    }

    ADC14->CTL0 &= ~ADC14_CTL0_SC;

    return (uint16_t)(ADC14->MEM[0]);
}

uint16_t Son_mesurerAmplitude(void)
{
    uint16_t val, vmin = 0xFFFF, vmax = 0;
    int i;

    for (i = 0; i < NB_ECHANTILLONS_SON; i++)
    {
        val = ADC_readChannel(13);   /* A13 = P4.0 = J6 */
        if (val < vmin) vmin = val;
        if (val > vmax) vmax = val;
        delay_us(50);
    }

    return (uint16_t)(vmax - vmin);
}

uint16_t Lumiere_lire(void)
{
    return ADC_readChannel(11);      /* A11 = P4.2 = J7 */
}

/* ------------------------------------------------------------------- */
/*  6) Pilote du PIR sur P2.4 (J14)                                      */
/* ------------------------------------------------------------------- */
void PIR_Init(void)
{
    P2->SEL0 &= ~PIR_PIN;
    P2->SEL1 &= ~PIR_PIN;
    P2->DIR  &= ~PIR_PIN;
}

uint8_t PIR_detecte(void)
{
    return (P2->IN & PIR_PIN) ? 1 : 0;
}

/* ------------------------------------------------------------------- */
/*  7) Pilote du Buzzer sur P2.7 (J13) + motifs sonores                 */
/* ------------------------------------------------------------------- */
void Buzzer_Init(void)
{
    P2->SEL0 &= ~BUZZER_PIN;
    P2->SEL1 &= ~BUZZER_PIN;
    P2->DIR  |=  BUZZER_PIN;
    P2->OUT  &= ~BUZZER_PIN;
}

void Buzzer_On(void)  { P2->OUT |=  BUZZER_PIN; }
void Buzzer_Off(void) { P2->OUT &= ~BUZZER_PIN; }

void Buzzer_Bip(uint32_t duree_ms)
{
    Buzzer_On();
    delay_ms(duree_ms);
    Buzzer_Off();
}

void Motif_Environnementale(void)
{
    Buzzer_Bip(800);
}

void Motif_Intrusion(void)
{
    uint8_t i;
    for (i = 0; i < 3; i++)
    {
        Buzzer_Bip(150);
        delay_ms(100);
    }
}

void Motif_MouvementNuit(void)
{
    uint8_t i;
    for (i = 0; i < 2; i++)
    {
        Buzzer_Bip(500);
        delay_ms(200);
    }
}

void Motif_Critique(void)
{
    uint8_t i;
    for (i = 0; i < 6; i++)
    {
        Buzzer_Bip(100);
        delay_ms(60);
    }
}

/* ------------------------------------------------------------------- */
/*  8) Outils texte : flottant et entier vers chaine                    */
/* ------------------------------------------------------------------- */
void float_to_str(float valeur, char *out)
{
    int signe = 0;
    int entier, dixieme, idx = 0, t = 0;
    char tmp[6];

    if (valeur < 0) { signe = 1; valeur = -valeur; }

    entier  = (int)valeur;
    dixieme = (int)((valeur - entier) * 10.0f + 0.5f);
    if (dixieme >= 10) { entier++; dixieme = 0; }

    if (signe) out[idx++] = '-';

    if (entier == 0)
    {
        tmp[t++] = '0';
    }
    while (entier > 0)
    {
        tmp[t++] = (char)('0' + (entier % 10));
        entier /= 10;
    }
    while (t > 0)
    {
        out[idx++] = tmp[--t];
    }

    out[idx++] = '.';
    out[idx++] = (char)('0' + dixieme);
    out[idx]   = '\0';
}

void uint_to_str(uint16_t valeur, char *out)
{
    char tmp[6];
    int t = 0, idx = 0;

    if (valeur == 0)
    {
        tmp[t++] = '0';
    }
    while (valeur > 0)
    {
        tmp[t++] = (char)('0' + (valeur % 10));
        valeur /= 10;
    }
    while (t > 0)
    {
        out[idx++] = tmp[--t];
    }
    out[idx] = '\0';
}

/* ------------------------------------------------------------------- */
/*  9) Moteur de regles enrichi                                         */
/* ------------------------------------------------------------------- */
typedef enum
{
    ALERTE_AUCUNE = 0,
    ALERTE_PRESENCE,
    ALERTE_ENVIRONNEMENTALE,
    ALERTE_MOUVEMENT_NUIT,
    ALERTE_INTRUSION,
    ALERTE_CRITIQUE
} NiveauAlerte;

NiveauAlerte EvaluerRegles(float temperature, uint16_t amplitude_son,
                            uint16_t lumiere, uint8_t pir)
{
    uint8_t temp_haute = (temperature >= SEUIL_TEMP_C);
    uint8_t son_fort    = (amplitude_son >= SEUIL_SON);
    uint8_t obscurite   = (lumiere < SEUIL_LUMIERE_FAIBLE);

    if (temp_haute && pir)                 return ALERTE_CRITIQUE;
    if (pir && son_fort)                   return ALERTE_INTRUSION;
    if (pir && obscurite)                  return ALERTE_MOUVEMENT_NUIT;
    if (temp_haute)                        return ALERTE_ENVIRONNEMENTALE;
    if (pir)                               return ALERTE_PRESENCE;
    return ALERTE_AUCUNE;
}

const char *NomAlerte(NiveauAlerte niveau)
{
    switch (niveau)
    {
        case ALERTE_CRITIQUE:          return "CRITIQUE";
        case ALERTE_INTRUSION:         return "INTRUSION";
        case ALERTE_MOUVEMENT_NUIT:    return "MOUVEMENT_NUIT";
        case ALERTE_ENVIRONNEMENTALE:  return "ENVIRONNEMENTALE";
        case ALERTE_PRESENCE:          return "PRESENCE";
        default:                       return "AUCUNE";
    }
}

void DeclencherBuzzer(NiveauAlerte niveau)
{
    switch (niveau)
    {
        case ALERTE_CRITIQUE:         Motif_Critique();        break;
        case ALERTE_INTRUSION:        Motif_Intrusion();       break;
        case ALERTE_MOUVEMENT_NUIT:   Motif_MouvementNuit();   break;
        case ALERTE_ENVIRONNEMENTALE: Motif_Environnementale();break;
        default: /* PRESENCE ou AUCUNE : silence */            break;
    }
}

/* ------------------------------------------------------------------- */
/*  Programme principal                                                  */
/* ------------------------------------------------------------------- */
int main(void)
{
    float    temperature, humidite;
    uint16_t amplitude_son, lumiere;
    uint8_t  pir;
    char     bufT[8], bufH[8], bufSon[8], bufLum[8];
    NiveauAlerte alerte;

    WDT_A->CTL = 0x5A80;

    Clock_Init12MHz();
    UART_Debug_init();     /* P1.2/P1.3  -> PuTTY (debug) */
    UART_ESP32_init();     /* P3.2/P3.3  -> J11 -> ESP32 */
    SysTick_start();
    ADC_Init();
    PIR_Init();
    Buzzer_Init();

    delay_ms(2000);   /* stabilisation du DHT22 */

    UART_sendString_Tout("=== Station multi-capteurs MSP432 -> ESP32 (J11) ===\r\n");
    UART_sendString_Tout("DHT22=J5(P6.1)  Son=J6(P4.0/A13)  Lumiere=J7(P4.2/A11)  Buzzer=J13(P2.7)  PIR=J14(P2.4)\r\n\r\n");

    while (1)
    {
        pir           = PIR_detecte();
        lumiere       = Lumiere_lire();
        amplitude_son = Son_mesurerAmplitude();

        if (DHT22_read(&temperature, &humidite))
        {
            float_to_str(temperature, bufT);
            float_to_str(humidite, bufH);
        }
        else
        {
            temperature = 0.0f;
            humidite    = 0.0f;
            float_to_str(temperature, bufT);
            float_to_str(humidite, bufH);
            UART_Debug_sendString("[!] Erreur lecture DHT22 (verifiez J5)\r\n");
        }

        uint_to_str(amplitude_son, bufSon);
        uint_to_str(lumiere, bufLum);

        alerte = EvaluerRegles(temperature, amplitude_son, lumiere, pir);

        /* --- Trame JSON envoyee sur les DEUX UART (PuTTY + ESP32) --- */
        UART_sendString_Tout("{\"temp\":");
        UART_sendString_Tout(bufT);
        UART_sendString_Tout(",\"hum\":");
        UART_sendString_Tout(bufH);
        UART_sendString_Tout(",\"son\":");
        UART_sendString_Tout(bufSon);
        UART_sendString_Tout(",\"lum\":");
        UART_sendString_Tout(bufLum);
        UART_sendString_Tout(",\"pir\":");
        UART_sendString_Tout(pir ? "1" : "0");
        UART_sendString_Tout(",\"alerte\":\"");
        UART_sendString_Tout(NomAlerte(alerte));
        UART_sendString_Tout("\"}\r\n");

        DeclencherBuzzer(alerte);

        delay_ms(2000);
    }
}
