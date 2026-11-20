/* =========================================================================
 * Test isole - Grove Light Sensor - MSP432P401R
 * =========================================================================
 *
 * Materiel :
 *   - LaunchPad MSP-EXP432P401R
 *   - Grove BoosterPack
 *   - Grove Light Sensor branche sur J6 (connecteur Analog)
 *
 * Brochage :
 *   - J6 (Analog) -> P4.0 / A13 (canal 13 de l'ADC14)
 * VCC et GND sont deja cables par le connecteur Grove, seul le fil SIG
 * (relie a P4.0) est utilise par le microcontroleur.
 *
 * Fonctionnement :
 *   1) Configure l'horloge interne a 12 MHz.
 *   2) Configure l'UART "backchannel" (P1.2/P1.3) a 9600 bauds : meme
 *      cable USB que la programmation, donc rien de plus a cabler.
 *      Ouvrir PuTTY sur le port COM de la carte, 9600 bauds, 8N1.
 *   3) Configure l'ADC14 en mode conversion unique sur le canal A13.
 *   4) Toutes les 500 ms, lance une conversion, lit le resultat brut
 *      (0 a 16383, resolution 14 bits) et l'envoie sur l'UART.
 *
 * Interpretation : plus la valeur est elevee, plus il y a de lumiere
 * (la photoresistance du module laisse passer plus de tension quand
 * elle recoit de la lumiere). Valeur basse = obscurite, valeur haute
 * = forte luminosite. Cache le capteur avec la main pour voir la
 * valeur chuter, puis eclaire-le avec une lampe/le flash du telephone
 * pour la voir remonter.
 *
 * ========================================================================= */

#include "msp.h"
#include <stdint.h>

/* ------------------------------------------------------------------- */
/*  Constantes                                                          */
/* ------------------------------------------------------------------- */
#define CPU_FREQ_HZ     12000000UL

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
/*  2) UART (eUSCI_A0) sur P1.2 (RXD) / P1.3 (TXD) - 9600 bauds          */
/* ------------------------------------------------------------------- */
void UART_init(void)
{
    P1->SEL0 |=  (1 << 2) | (1 << 3);
    P1->SEL1 &= ~((1 << 2) | (1 << 3));

    EUSCI_A0->CTLW0 = 0x0001;

    EUSCI_A0->BRW   = 78;
    EUSCI_A0->MCTLW = (2 << 4) | 0x0001;

    EUSCI_A0->CTLW0 = (1 << 7);
}

void UART_sendChar(char c)
{
    while (!(EUSCI_A0->IFG & 0x0002));
    EUSCI_A0->TXBUF = c;
}

void UART_sendString(const char *str)
{
    while (*str)
    {
        UART_sendChar(*str++);
    }
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
/*  4) ADC14 : lecture analogique sur P4.0 / A13 (J6)                    */
/* ------------------------------------------------------------------- */
void ADC_Init_A13(void)
{
    /* P4.0 en fonction analogique (troisieme fonction -> SEL0 et SEL1 a 1) */
    P4->SEL0 |= 0x01;
    P4->SEL1 |= 0x01;

    /* Reset et configuration de l'ADC14 */
    ADC14->CTL0 &= ~ADC14_CTL0_ENC;         /* desactive la conversion pour configurer */

    ADC14->CTL0 = ADC14_CTL0_SHT0__64       /* temps d'echantillonnage : 64 cycles */
                | ADC14_CTL0_SHP            /* mode "pulse" (SAMPCON genere en interne) */
                | ADC14_CTL0_ON;            /* module ADC14 active */

    ADC14->CTL1 = ADC14_CTL1_RES__14BIT;    /* resolution 14 bits (0..16383) */

    ADC14->MCTL[0] = ADC14_MCTLN_INCH_13;   /* canal d'entree = A13 (P4.0) */
}

/* Lance une conversion et retourne le resultat brut (0 a 16383) */
uint16_t ADC_read_A13(void)
{
    ADC14->CTL0 |= ADC14_CTL0_ENC | ADC14_CTL0_SC;   /* active + declenche la conversion */

    while (!(ADC14->IFGR0 & ADC14_IFGR0_IFG0))
    {
        /* attend la fin de la conversion */
    }

    ADC14->CTL0 &= ~ADC14_CTL0_SC;   /* efface le bit de declenchement */

    return (uint16_t)(ADC14->MEM[0]);
}

/* ------------------------------------------------------------------- */
/*  5) Petit outil pour transformer un entier en texte                  */
/* ------------------------------------------------------------------- */
void uint_to_str(uint16_t valeur, char *out)
{
    char tmp[6];
    int t = 0;
    int idx = 0;

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
/*  Programme principal                                                  */
/* ------------------------------------------------------------------- */
int main(void)
{
    uint16_t valeur;
    char     buf[8];

    WDT_A->CTL = 0x5A80;        /* arrete le chien de garde */

    Clock_Init12MHz();
    UART_init();
    SysTick_start();
    ADC_Init_A13();

    UART_sendString("=== Test Grove Light Sensor (J6 / P4.0 / A13) ===\r\n");

    while (1)
    {
        valeur = ADC_read_A13();
        uint_to_str(valeur, buf);

        UART_sendString("Luminosite (brute) = ");
        UART_sendString(buf);
        UART_sendString(" / 16383\r\n");

        delay_ms(500);
    }
}
