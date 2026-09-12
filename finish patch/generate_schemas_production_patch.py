from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import warnings
import zlib

EXPECTED_NORMALIZED_GIT_BLOB_SHA = "99fa87b9360886b6588ec7c65b120fe4ab1c26eb"
PATCH_NAME = "schemas_production_hardening_v1.patch"
_CANDIDATE_PAYLOAD = """c-rlK*>W65lHfbOA}0C3s%fxzNSv0Sfov#(?BOg$s(EO4Rt76eR3(6HR%Mnlvp_*@ZPq-+=IqOu?b|%{XxRiIf*gpVDC$cJulptI?r~&9WJK11qQveMWg>yh$T&Pa{C1D^EbX(wb~j9lxWnT9Ak7N)QJ6;`r`@Qx$j--6ue-?3rpbD|u@ZNRMb^hR?X9pEcf%sh7TK9z9Oh>?)3_7mi)<agC|@tE>m#(*he@Z1(<Ib-$kn*fdYVO_nx7WigE-lcO)d}k*Ng08oWo?!B-{975oP%7Op>HUSVS;mKG*9BwC4Rlmr)V-BiWPueUahcU#1ECgwI6ls1x_Yo@~6re_do35}Nkq0St&US!7o(U%#}{{^v6n&$q9CvaoQ3El>Oh8lPyfkJ4e%4YO@F$l`un#9L9${_h|EH(L+m9_#ed9G5f5qCCpBBDV4o{@jUk8azz8EQ@{@bqWRz^KI5iqpSn3TGLIWz4B4}!li5NkI(!Mw#-hoPrm!>_Pg)B)BcBdf4$KD`0}N5|Jpuzs{M|5FQCx~-j{z`@PE*hO@Dj+%%y93yA!PwCr-lqg@sNp%yV`n`g|DW1>smjVOw))fx(|32=EaDT!6JvL$-45a=yfd$&DnvnE+7YC@DCm<t)r1SawomAwXd(PJ6U5c?<fX{y4sN2!ml#B`P<fFW{r)00vr%yEMHcY_vPtJ9u#L@Zc^ReSPqd9o&YW?~R@?`0Me(-Ghhl<LD9m@F%%Ee6u%te(+%Q9DY2w&n|_Rj$eR5lDOE$m#^9A`RMh*J$4C@jKNR$p(S=UdIkUQv=+M2I%`w=s4Wn$v9-i;`|n|sd%g5#JAsdv*jk$QU=ioTULG~su@BXO_)N@Zl>;$eXIm`J`H%p}1|Uq57h%$g8e5AjFR~^f51bda)q-E+L8B=)Kzy$as~+Q@EGmXsLOm~7&x{Q}0T9J^MYdgb0L#-51IBG^HP!IcD*B=m4GPw%o-`l~!{}U=A<enAJ>WmWGIIQ;93l&2z@D;kBXI8FkMPev8@;5B*c&|wnv709^d%vPz<~+3;#}-bqj~6ISVKpTrht)v9}Fgu@C7u7|K0dk_9jpfQ0gTceKUGI+8OOK`0E>Z|9JEbAte0pEu!=5(RZVL?0{ojrx%3@E)0>PO<O@YM`#7Vs?&Hi%3|1xFC!K*4hME=*oTLm#>rEQ?=+8f(*6MUXss8qErbVdNys`O;7;6u1M<!>NltO6lMQt=IW|;KzbQ8$T+18qw8=hX78R=72ZECX8~vhzZWsQ03co%Weal8K047h&#ki1G><-Y0epujyTAvS*oqZWKbc(mgG9=}&z-5CeG#6R09vIkdBlqEu_~15fJnT5UybJ&ALX&Thgy}eK5jReYH0(LJ1)c1Veq>0>fQpSC0sdjfuUH9C{v$N!!y^`cJ$eRM^(P&tl3}mc=3DK=DFM$QFv(N|G>vhRV4ngS33qGXoU;H$iTa$}?!#ifuS^>k_yS1r6Qt}9WS{u=j(H|%{=kiqRywACSlTL=&xzzj2La#zBRhek;g3@v2MN1pw8u~7Hok&?ZyQHM{_+9{$Ai(HNuCaS04x+N&nVwg5J1lT=G+xF`cGn`0uKQPU-DVqfmuDkRp9Qy;~jW^mvcnEp_P;UNtzcMS#<Tc7X_2W&FB>E?pixeiUzGsFk1Tg@A*G{*oOYFzr>&sY|9DpH2gw;s)<beebgTm+pu@*;jmXMm5dphuR?pomc<3aBzQ76E^Um8ePP>6KBjH7o`l%IQMwJg@sQIUkXHb_JIE~M{LLBTW;7?J&Cu=B(GG4N?Dp=#9Zq*%!x4QB?fwn<+#a;q!(ZM$VL}7VjKYLG&VRQ|Z;BMLGTO+vax@$xZp;iyln=z&5=Sbq2#q)ZCApEf@1M@P#dhl`jUX<p@q01QA6l*7iy{7Ci9~o#Q3R00;}snHhd|?z(8CV=`@yZ_uv&?s(Ct&iPd56V(-2Mv1ZCkwV36jdWeF+({||<RPUzL~6jQLM2B5i^_VUT<wC-3ap%_fvlt55QqK$A)vpP|o)h$F;f)DJ_zaxwEPbQBylBhd}c^uP8q(q@*?IE8hP7b(r3`Z2?OrWhCZJ9VrJAg>Q*KbMQbO&1RBKG2j-;rC+ar!QyH(%MK(KF)sf5rh|7i5nJk;fzy@9I4N%P33RgRpZWcP{n_qjzl}Ani_=6(F+3DCClIS<d|f)=lZ8Z^m8JO0#S@AX7ug*0uq%J<wZwsHG=cQC5&$qhLkKPPTNAdN8!QtuB%9F&w>JTqBqDkBKw)9Kdl`a#};;RRZ5G@KpR}hZC}U5<q#lu4IxbJ_z!=^pnUjKC#|S{s2nw&j|*yfo-X%@DeG|bQvec(+N0-l<jLZmN7Cu$Nbyy{2fi(b1)#mY1BezhBcfr0yvknILP6k;-P$q<_*L!czg$h@_l|7-*M}qCZ$&sTbKpU-Kfpgfk)8KZ6XC+>v>6^5HHj)JQV_)WrC@*vUt#4H`y#-%Z8DG|3coY=mW~2^2<5-<(y1$PBdi~IqBokkH-nkY599Fy9YvnHck(`g99`A770Cn^bP9C;?SY6a3A?5Q>IPhVDV#v*4a1%S)mW(ZI59Mht`^>1AbLm5#V!ivkGU;(e4a0Lv(sh76eX7NF*V#;s?2dLYZ2I^Fkn(n}8zA?a?cZz|@OVN7yIQ#$RkktOxR7XPYZ*$JBJhV4!FX3zkG6M8N4BCY`W|0FOiAS~<Qs+z_U?96E!uxUtFBdnxGd&DMl6<f5r7;_@Vv07HKOnA{RpM}rUp4bd&=8d53(4f`*&aYb>9=!?QhZee~7gLW<HMEt3u)^vCz4O~ugiElNHlv_NPOPtjK%wGbw(+r*9(@r4*uX>s_YZc4`nmk5K6zYXGTLDycC~ctX_N%!9Njqu`H-1)_iFwh>8K=TYF2M2*j&4pt*f(u@K*QPRA5fZ`JyFSo{ZJcY`gR`p)m#9=kGOxRxQLxW$5b)wMpYu9@SP6n>Rio?>TLY{rV|^gmf2)Fqsc#(-lk*kp9q?ztW>%u;qf%{(NPz$$dHa;43dvdSSC@TsxAXX+4(Et!1F<&G}-tChjg&c4Tny?=SCuWKFy43u?TuYG@?%H@Mw=@8IsGS0Jhf2wgH&7N&^Gj)g_>PvXOJ??cgh*heExljZubjfEvP0pcU`BJqYvsW}0>9$2B~Yn}9_~W-vqVPCIokN*Y@&5Tep<)Ch*f`my(dCOQ^>eQNq4OfTYIxjDkvhkySFJu~|G;b_-lIeueiMVylMExzp&i&hD`YS3p}3R%jk6nC9;1N{_lhH8vAYkeYKt*l)j=ZXsC!C5WZfk6#tPtDZ@81a&@qfXe9&+-bLT_ro{g#9>-rqG3it$%q2^sC*D*+&@Sq7W+Fy>edQ=+~4*uph};rtQe&NYK;As0?1fUyQC)2vr4i6@?5sxgw<4X*+YNq}oP!x~rIXJhQY-M9}lJ0beIu7!8DEM5vSdg1iek<S|j3#&4nowQY7K$_HtZM|pF)fq0zN$5Eb#8<Fg!5^B}w@0ajMPrZ^;)=FUFFVW0SHWpF?UyPnAT15tEWRHzA!(wx$)m%(B;zWdwHS`cNu^I|PNw(Wa;%P}3D1|X%jaI8gs%;y%z(%pTe2Ux=^0(6`ICUO^_ML?NslI&=6y<J|cYp*UYAgpBV;}<#?g0dLft)`-xF;BZ<goQayleI8WJ2gq$1eZL3b<?pIvj#U7RYr4Ja%(ASR>pPQ~D<YZa*qE)2=XTBI}i8C+<cGkc#a_r<X4>mtdgV6D;M^J4FeHDW)X8j!G$Iq8U|0n=%Sf;L{{$gJj?IMwFDlX3=^U<(qBmaW@0foB`M<PC$R8P>b`}yd8F7&v{6nfxqHgc7*-vSHEJTZ-GRJ6ZRFU*QDp7VedZ4ccp9W9tk~<d2q!8aq1qAzQaffq%+u`=cI_S9+CT0n$*c#cAra`_fXv6!~Bt5{Vj&v3K;~NeoOMoUtk_M!nB0s9h)S+rqLdf<4>UccW{vQ5AJZv!q<AA%V4q%%0jPc+KsE5A>iOlH0J7NIzUXQpu@C;;pFLh%CJY?xDwowKx_hsYA3_~T9hrBb}%(CMUv=aoe~5r>~;Yq^C`YNA-<I2z!KBs2_?TN9uKcIF+qFZA+@gEi<27@kA7MX4qP~zeA4gIq&;+HW-^B#&Y8q%JBd_SY!3ctzzZJ`1ZJAIl1O;CU0zv(!<4G8#xlW{#1Rj|*(?Hr+mL5M62{5nsmrbunYB98=_JPB6Y(>IVqqL7^7KN=Nhn(gSG8vMUo!OOuYn-E<l%nm$Z>M9gCvaLg(U8K`h?=mZp+5Ei5z_=sVHh`FX&rEL5EoejIq5I_E0Ta(u7F>bX9z;1lu+d#q|(CMDcF4Rsd4;<6;gSB8TaqqM)%De3o@K;bB*MD%}g!ptbkke}BxLqqU_S768q)At14EcZ!|AmW4^a9%XX(YlOE<G+C0_9G?YY2dzgD3JC#Ea)6&#P5Nt6*nNQ?#2rwq-cgEon5W6aH0C4#(eC>NQ0g5avU3~#BeYtecK+Nii}8VHI@<ixIUH!Q8J}cnci1UD<&i3Wxo66)wokE$gt5dOae%esS$m8hOUW7aA*nw+Ca<nAladPseii3fo=b|_)uMDJJV#~3FB~Hwshi<GOXDm6b{J7})tV4Konbl@B6WwvtNW~!gcy+|p<M_W(C{Ur6NKnmLz>%m$;bp?JNODa+M!UY#|Qt`6bSNZoX3U0l8@u$C%_DSV1rA{duS6Gy>gP0XzIl<)eO^)fX3qXI>}2ZAu0LFvZ#2(tlCz!!j@|1=B9d!xpACe&MYyQfGbU_WW1{@8N1{Rd|4VNxB{~;$;&OW%8)KWxXD(cB8+>p8DXdg(ZSr2{3k{%$C54-QGc#W8gL5KmgGV|$2|6>*e;)NI$eFfmL@~j^E~VidXfKyqd!am(3u$LM*F4NOUs<Ng*GlgrT?;}Q7s9BVsA!I)rUM@mH1&9fk`d|6g(AcE8s8*t}qAbutJRSec;*v4HYa7VM|ca7o8qpnUn!Z#<8-68zcuE4c9@&JK9uI&mbKPduZIzr`5=#-a5%VM|}u))X0Uv_APt%Mj8aQ(8qukxV|#l*fJJ=;5rFc==EE87Wll|#r7c5?N?kRo?IZ|DkjIIzzu-8EPb&=hqZ0m0SzKsIG!?*N&FM|h14s=Z1m-T6i~|`=jDXyu;`@ysD_*70HR@DLQmK%W(6MaqMe65Dd!)quTGe60(^TtQj!kMdPyo6gz@2f%7Nk81jNA$O{oe5?lvfa{d|eC{6F)Z{*wNPD7E%FNMmWXz1*YX01m9cUJYlgYYg)s*N@ViS`s;}OCnWMC;al9<aS|uc*?UB;eBI;P?@PPirM6mt04Nq$5#sgbB#hiyGc-zhK~TVZ(K_^HhOi6KMz{e)czbNhB|+gfVyAy78adNX;45caCKIQ_jKG1ud8v2$Cw!0V@_biki$!)s?2%SYdt<`TV`t+Xg~}!C>bc9e7idw^kR$#ZL6u2Tr{X#PM~qpZVuD@49`kS11J?_z=uG2Inz{Qtm<4CBQ2ndCI(UC&v{hP?@cQsu^MY(224K!5sR{?R46i!zI`AK0hYQ;;yWqAdV5}CK|rd)#HDE@qF{9cyKEi?$lPli_@&scVA7_N311eWFdpQZGl(7&r{)jMDbN;q`KU3x9H>K9+AeTWi+^z~SfitkWv<Hc&vd(-AbXK}1`mkKr%~6z={dVK#_8vN^WW^Ai8(k#4ncZr-6FP6Vp5wVXY$JN;d3<{%3Y$lN6cN*{Ua66$#g4t1J05udH+8cu1+%Gy`~th?@c=dr99r%4cQnHQgCVe5N3$KePvyL?X&u;qg1cZS8d9}1ayzEAh~@GI{17w`l;0RGGihK9tB;3>d-CA3lV{$B14u|&kViquT$goTYY~D2uc8QVP1goE!3M)b2FenUP(TJ@y@s5Abl-tTF<zZRocHW7-g5z^B#hL*Wl84ljn>)qZs%ymgSG^U#?!hB)mNs=R)Bn6fJ>K6b-%})x}*RntRfK`$u-ZH!MIz#?Fz3($R)~IDM6kJ_3GXtM@gq;jMt}<f0;y@m8Nv(43c*0I)0SN7+V{bhb5@t!+H;?nwdi#pjub^zl0~-e&uO^eD7BpVyWFe7mBZFS~4!sw;=Nlb%oNRpE^%F}jOxC$YTSju<gL6A0t|Ih1q^lGgZ^I#jE}2}D-z7fvu_D1h&|;H5Gd0uI~lgS$(ZcC|a&lZ^E#*XQs@%$|IJyjEB~h&E6b2alT90{ZV-v2Btu(=yVVNv)5L8j;{TrjbqVZTr+@Smrify-};xbmppZhq3M@kgNW{=j?Gx>PM}Qj|wULC_kM?You^qKZ-sTqPJPg$V@Yk1v)Le0VXH3iZA12J+0=0%0F9_T$n|JUI?A>*2}WaXA2lv)A$4{kNG+YbNOAv-+@f*XvKLds$^9y4wN9plPjpySsjo|Gy?b@6`QU=t-DX$kdAu=g)RuWqzY~^DYEhymYpq`db1G~C}1@31<XMgb6_I80_EydULFiP1!<+tbDP_|ey8T;afn0?2M?Xqs#iymcj?l>2Q9;YW41L&zVVUq#`krpnQI@4hu#rObzL7#JoS7f$hq;2cvk(wWF^Ko<}2&d&yA)k-&}{e_Oz@r#xYs)0CV!PIrjXy!wqM!8AmHMIEhrC@v@_5Q&j9gnm9@cNF|U=5y4*v%>=FZ3daUS_w_ajt#J0KAZLX}7+)K|2qubFft}G`cye_Oqg0+_6(A%S=QC~x#Tt2cbxW!)T1zfkT>`OGa{-1)#`765S>rR^-c;vBy^w4Hcz{Q(ghlAphWr6N^N9MgmFYu<ZQ1=*!pY*&Cqb2<s-|LzHQpCqE3&lkeq58^P;1Jr)4ug#U9M5DJ=zK)`At-CbJkf=yty((q7YKlaWDsA;g-lF8ak0l1mkh=v~53)A8cc!sWNY3k2K3amrlHIRp2oufWj}cq(=POPL0^5bl``hZ!B*ioc6}`0g6oAGIKZ+A!W$9d;l)|sJhuodyFF?^MuoI<864PObMa17U3h>D@(-fP%*fdqyON)KBFA8d%V#Lc>5J6lb6@g={4*{Elf4u!2%M}qja0=Bp845fYR-6<F8mkf)95eO%ABU?386EWZF5E)}!hhE<>hwSryBsqb0{XMK@14R0F;Aej~6tMT5C`BuI$RA)0kI)HzPX>{^=+y>Lxt$~f&)r%!tw3Pz7J1z;OJ9Nt$jg*R8_x`6<yg+T@80S&6Mv59}^fju$K>uP;M#q3{@$Dxc%Q)lXd>7%7XBadb&X26lFJt~?vmYcviq;n-Zn0U;7Wjr>qN(X`2*@x_e%2L<A7dTcAmWqJ49+Y9!oCH5-GA97*$=#B4>LIT!S-Nj_v9<@*ie<ld#hL*T{X;7-25kCQwOrZK>e_V6hK?OJKut)(({V#h;j@Q-UJ2hkhro^~jY?vy!UbvTxkD9@?v8WRYxa&e$)lzwcsh-9(b_jbWUJJ*N>&X&h>ChS_r(BRviQkL*bg`OkLS5y(_V?zqfSAIHtO{(Ni?VG67{r+&6pgczOVN~AGVf-Ua;MOM#ZwDYFWL#sX$W&6p`N^YgkfF3-8qCMcPqxaHBEwW<K-<%K-ynemzeL!zJmOSQzCCQ)lXG*rO1OOR4+`i_e1&K>=ll2_~s}faC=*b4cB_9Y02a4Ci$&nr~-(W4|?=J{xBWcLm3I4d65N=nI&cIU$$6{CR{$Zcyu`8*#@zrv^f6Cv`K-+Z5P_&P0^I!erZ&eJBc09oY|gO<H<ro#qdPW}^fqJ6f>Bg@vk|Q;`FQeaAeif}#G{BN)y)8G&ft$=I`)W_Z!JHg<)03KD}<k`tGT8$=1V+9|8ZtzMEUizI4gTJ~gQrKn&hE(v%*)b}|vYAz^GJ>Ah_$n;UqwFW^LE32?j5FjPiq!T8+Ae&K+ZE^vgE;CX~<g?-WJ*D03kU5pFTr7|*uMgFAF(~)*lrgflemD9L7Pv>j)J$P8FqMMi(yz%`7Uxt}=TvX@0k6&fn5w)zX;sH*+F-1T?j+V&sJv|JM4Ty2f;C+Gfu&Of2SP<?Kd(tORC)5Rje;b1DJtU!s<v;S2xfX?&0EPN?e#R=CiYsisC*)kN%5>nKX8x-yNP{-X;)@POh*>tz0v=n=>I2mXv)#2R6F_QIJGDyE=drzlCcPS9e$ZYk}Sjkv;(#K$Bx|W+uT@y$&+WO{(#IlXp#w3gd5Wv@xp7P=JgBOId9fp$D-m!-2(o+KGp&4>*RCxnWLw)$-bxAWU0>JUYX9mha#xV+;~I*Px}N2EcL^Vvz0g>V1)Nf=2<M9m1ZDhD6o0u(<7`>Bo_^vm^zNZrbN{+W`O~Ye9O!G;B_%r?V5jyRfeA)d{yo#Rl$}vR=uh?7B3$Ch1c2G9sR)Za~~5SN8d}cD3+a&lec5!6rxcGn^s&@FTSv+As8SrQ56+eW)vW9(6Y!d^*ucLb9qVG_ptW=#RX^n{t-p10a%*BqR^RDFg$FR@*_CY0S*(}I6iqm?4PF3SV^NwuTeLoGz|N-;5%wR#RfJ_my;uMHU&Z06;Ig@<HY@m-?inBu|<0r4+LCd+A86PTeQ7Tg!zmr;NOC^-QhveR791IoV*qWp1;EQKQhwaLKOT@ESF~97^VV-T)wu_CNJOi(ln1WH&@vLq2vA*-*~?(!RP$AeC_N(M@n(@FC^>fTu@Rcp|$nO#*)#>Id2y!Q0`vOEI$Kdtzll6_O!$h<SMfC@jgG}OH#;02lyU8xQO_7j$!>3MDHEC<6)m0nYo=+d?L9iedMl$wiRv09nc+m;ab$It}IYjWtH6p#)h1y(8U<2%3Ss%`eHzmO`8OrIB9Q&$>F0YsWTdsgzP!?hmzId`djb?;qOs`gd`D2@?S9h_9nN%U4Ev^8gy_-GIo-3GcdG<DqHGj)iG~3usr2H18QKR6!(hH?TB||%uJh<0gG-8I~^ba>%*Qz4gIb3mn#D0BT7Zli~7JV=Qe2{4KgAP*45ctvJayXKVU)C88uL4`D62bH3+Q0fmln!tjnVm=9&>9Nc2*L0f@H}_DinKSg?|Q)ypdpUTi+siMsbpFc`EyO_5*!^KNa)l|Y2}uIk$p#X4?reF`J3s<fx12YGt~0F&smDXGy|EOW<)>R_Ed0vErkhJ@1PBo9cie$FUw<Hu67;Wa^@G2zs7=TlsXVD1a1aff0^w<v&AgvK6iE*&OdR`3feEartMjcVNk)S$Y5ceLucGNDe_M*js)?nH4fZeJoSdWeM8>(z6Vs*^&_b6IidH7_D#2=#$hkC9I9c+HQ`g~W$R4D{-(w0{?3Sz<y_102&?)Zai!&!5{A@7{n(s|J&()QvItD4MY<mK2>ish0*2nMNio3jY&;S{pg3Dwi1Knds<Bxa|~5l-$4KB;KOMdd5R|Yx?MHM%^I*&m!_Dc;#o)A@VLQh*2(S3@>#r%If1&F5geoiO>NYy@<@e!%gKvQj_V20o^Ln(Xpkg8i%#pnQ&Uw^%}dW1&&pnxY=#3MX%cHxsncReWWT4sY)=lnmpB)QYCZ0J;G2D=!uJ0g_k;KVS=htFYd$z=;Fhy6S13N7Hy`(Jo-S~lols&2wAWmXL%t^i)EvrCG>dww#*IiP2wWIo{bnDy9rYOWDW-ucs>x<xOMq0Z8xIr{J6M_4F&`HbW^$Py22PQC|0*+%P%N#aXMl17C%|;!Z!}G>>;meuvtp6m)xTt4l0zkoIK{~xkECXffm32!-D1JvND69<FVC5)ZE+`@{r{ZlgeIb%pGS9^ll?6n9%KXrv>2qlC>z<1Z}eD=F7sHZP@Zf`hnkb7L%NV&V+_FYi;CZ&-EyxKhsqK4@AyF*+a!6gpFWmob^Qh9bU>-pA(f3-Nz^k^5{Gpz0xh+6!q7#oG38bXD~1VMghR)vCyUrx8R4}kj}kCQkTN&HFX&wU$s`sH+7aaqHGsoE8f(!rikcQQ#jN8-7qgubz8v_GSf?`RzVu=dYf4)4N*`Kb*aS~_$KR!4KijkQ7Dl4h2wVB^0KX${AMKdY}H5m@OjdHtGU;(G@3$g=NVXwU9Gw{>We*{u2!2S>-b-|*0Li`+-ox7-_>tLDDSyi(4q)tEg2={0Bu8S;NvM6rIC+H)B^|K8z~mGD?9}IdhsU}e9GyU6NKnw-yer21OU5m)^r&)GZlwoWq!#%#a+DC@BMmJ>a@4eAxA#A242}AAW+^naf{ne5AH~J*h|zlo4R9Ux*Q%#c0egmQ9VmKtgUqG*GD|r+_EyMJB>S#74!!eo!R^1Jqn~3y584#H((t0R-(1T*FuKVjs0AlOJU{l<@v3e{<3=Auy=z8e&J^LO6G~ZKvd(>Y(LzFAwez;@{^~64@&X$xRm=q;01XQWZNDvnPh{@zjUWe5wFEP;J2+>fR|Rk>dLMs@GplGF48P;pq8nc<9f#=tYb-&8Dv{g|D-;;SYBjXEpsJXl)^n`lVkJGPA;vI42-|Duw+Blz~EsZ1~~$@5#&LW8@!z26N!CJS+N|e>6Q2Sp3DLeq0dcfP?=-kwUNv)77APb#Y=pf2_M9_{`Hp^DE<WNuerK=wm@%SN1I`?p{E;F35Y|G;|QfzTBc=d+2ZCKd5k?epfB`H5B^pcm{P0_-M}fXV;A>i%alHT?aO#E5P<gvD<FEf8t)?r+{Fhy%+C3dES2bGfzGc~OtmD`Ri)u@(d7n99dC>_x#sxxCHok6J11V=s9nsdu})}+OgEI*<fz#CxBrGI!YWnP5q}Wdf4G~ZXw-=&YTL?@%%Lyai18C<!U-fniG}*_mrSvl?1nWm9B;rs@-z|V#hOmYEPcgrc{_z<;e$JubZyB?gxllFxy`$VsK{Q`WVGVM2tP_G13`-?Y26HC3{j$8FY`+bDX9u1`}$ec)By``Tg@t2UYF`OPmUGJ-kjahF+H@^O=E$y(<k4w4brw%%-__gnG9>~jDKZj#2EygAstRl%<-L8Q`l)Zl5Tln8i7d0dnN41(^%h19mM)(B|h2BnllJdqVPeT09C0sF`2ytL@DmPnx823wq5#YQ2L1$Tk8z3UANE6syM~XD7w+36yScE6r23V&M+_1zQr8;{@yWni@N;4xb)QtOHa#zXWA&INb*x;zj|new%=ok1eGMKJ=JP!$Iu7?!TMHepMEwHad3b1if1j2Are9joFQ^S^l+}rt2C->JKo3%oJfiD*O0GO<Gjahj3Vc+9dFy*yz-n~bX0y|s9lyH!zg~K8^P-86zEzVS5owWgXW@EuRth_^!^P_Nz+SlM*67be8v#8`D$Np4~26dDwE8Gy`D+wg!JhkOem--+0>KNhag>azal7m-VxwE@5Eks-tt4@{Zz+KPa_>=7Cp6F-W<Udek|=`<8j0mb~G!(4Mk|3f$-BQ<ESR<E%5jGtLs9KFgteSEm^ub>dDvYlU0O|>&%!kb^H=+2|u3~WztKry*1hmkXG$*ehb~$ayO=gElLWDuP(@H?*^DBFYwZw*5Xj^oZaN4_agOjYBP~m-2*$fXizkbU+7~9eVuRZZ`NQurD6B5hT30jv4^$AmiRg*V$)4z*5h7OM;iiunGJemF#B89e8cLs7^Z)4E2!4(Q>IpVSz6^tO?q1zUf1q756HRCv=jL86zJmIg|V<%D1*J$FvXomn|Ze>2m%p)8uRwt0Z*YeH=;qo(xkUdf|ucw|9}mX7@*TtpAGX!jY$`e;lQoHeGTlGI%+a%#Wn;_onHUGRq~W<PP-J{q8{uY+`(cAtnuGv`0h*z_3CQ@gQ;L1C0kK19Yh~+m~(e5ySWJn!y{vkg&17St`9b{up4#FF;G@6HX{{nDoWrg;OjM$s#r1a5HlGQbRV<Fb*SUND!7azx=3U&i!NBiKqk%7HQT$Ca{DBh;fghj{k&UWQLdbserMRvrHct1<M&@)OglFw@Bt}<-kIww7p}E0UOxNZa4BcbUc2z=xj;qWE4)3^i?YHg%GVWgu8&O>mr|LTtB6>|W)=ax2B=q~RJD^-S2V$2!8^Y(th<=WTVf#G0wpzE>qXUETONdOKX)##%M1J2kIT+0k$UATJCL{vFE^wvM%@k1Rg>d4%MTFq$}3+cviC+EyLyUjNalmOyJs+h!kVNyku^K(IsT<HlPu1f%}>Ekx@tUzLtP=1I&h3hmm;m@Q+_a}L{m51ORtC7dCiHRkG|--#C;My<5Yzk=)s~QYF5hbu9G>|=vgVqe?<t=rLy1wXpQb_&iHj%0=z5-A}dd!!*Q1igFgwH&Wip{<6>zYbrC!T1%EP*Uca@P@VO@^{53Gh`v-qwRE6gL=)cM&+WS<(<@V?$M)K;5YwB!R=KLV+Ws)&2t!sF8CYq-DQCJ4FE(2dV9&;@?TUtvcM_SzYbe~djsjS&OUU4cIV`SA4`z_J%;2g|WMf}EaZo&i)$5$lq90-kd=?Vk*=4P689i+h&1@CY{kEtuS#OCqpJG?YLUbl>y;qq#`=%y(uj4x^I$%1}KC5u$u7g1W<NO0hxe7sK3liGt(FHY*FQw&4+no*IiXV_gZdGTTi*I7bW<hPR{=UOM*9u(zATW@ii^fU_C<m%vOs$}9G)rES89Xw#~;$Np%*(cjwly5rhYG*U*hdH2ztR1s2avdnX25A-7AZ2l&=a_L%*z-o_ZK(4~wLW~ca(URQEqF4<B$sTT^s#K3h@)1A;pP`bisEcrG{e7rNU2Y1Cfw9JI21XbvXn0Vl^cm|=1w}|pe^_rmt-mLyxr(S{#Xa-7@v_=ii6jLBVp|^COOq*#O)yAWA?{dCB1PDB)1vEh0$Yjrzf!>%>PDqhdo7Y=A>rE(|=9ohncWmr2_JE2U85;MQFsoxX?g54ta!?ZYXrIfbJr0=f_zuGXB7%EBv0vRY!QEkviz8Zp<SZ8%EY)NktcVQD&Whm?4I8adsc_Y>E!Fqv;Ec#3hR(9wj_%@$Z&Z|1+0_m1%rhNjuK9L_xck*uZ`2M?V~Vg;Ly(Suah|isMENP2iWi#0>YTV&}MG!{sW=Mb?uJZg!UWlk?$(u6J?XUWbF$PPd{gi@TAdTE2YME|V9>`YhEqynfsGk7hc2Y7}V;)=ym(f({N;S-$f&#R>%UBqg(jTCe}2)k(`6Q`vAr(evldUuJYA+AA#OSltnn?W$9#MN6&XxNCKa57)2IePiVK6$X_-k2?mC2UT4q_7$(6EN$iX?kyMDF!J6DRCCT$eU=(~^F&onKvgT^MBId0-&AL>4rHB<!_L($FmJtRD(CAgbU<a1Q$d+35wNz`K?kb4i}e*m2EKbs#|fQWt9pr!IZ@r3ZUy*?%sSP~2E_DxpjPiv>iNTi`?_>V>=NgrmwcNW!>^phI<7rCZ=Rs~0B6w0O~y@z4o>()C2d|S{0WuTruxpW_1e$!6LH&(hzpyDN4LUmw_%iysUaFyqE3X#T7H_L@NzQ(0Wdop&9H~RTBMyDMR)_P`n4enW9U#W`?0UQI)DA*#rE0D*DqZ|;r#5sp1pXk{Pojw|9k--Tse34@}*$aD~*hm6s8a={+24_%|hn#PU@m=PDF6gIAf#ff)RaF-J(x*Pp1%U^!|1ErP^ubqKhdeQxR2Ma?H$Rt2_lLWEp5L<r99#1nLZqmGPS-<dkZukh+o5C5PGekg+@BxVBPBi<54JGb~o35mg~PoMuuUeqV*qnhOB^6p?0DLlJe+tGb*iL#X~grc9M`NO<>ZUPGbujnN1W*89V1ND~<*Ks@n?K9wp-*soD0i5|?QPLfwr;U$gf)>jcF^csZ^-<h%x6$lk$kXKejud`R5c88#<iw3gxFpskFE^rg!->Y_GxXZ@g;utt4Fh6_Wp<I=YHT^uUstQJ&8Nh*n0VZ`?&One(|Khlt(s5Veg&6TO-4@Mwj{l0bY5upjPI$!sA9_YDZU"""


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _normalize_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _git_init_with_base(root: Path, original: bytes) -> None:
    target = root / "wa_backend" / "schemas.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(original)
    for args in (
        ["git", "init"],
        ["git", "config", "core.autocrlf", "false"],
        ["git", "config", "user.name", "schemas-patch-generator"],
        ["git", "config", "user.email", "schemas-patch-generator@example.invalid"],
        ["git", "add", "wa_backend/schemas.py"],
        ["git", "commit", "-m", "schemas base"],
    ):
        result = _run(args, root)
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(args)}\n{result.stdout}")


def _validate_candidate(candidate_lf: bytes) -> None:
    text = candidate_lf.decode("utf-8")
    ast.parse(text, filename="schemas.py")
    compile(text, "schemas.py", "exec")

    with tempfile.TemporaryDirectory(prefix="wanasah_schemas_import_") as td:
        path = Path(td) / "schemas.py"
        path.write_bytes(candidate_lf)
        code = (
            "import importlib.util, inspect, warnings; "
            f"p={str(path)!r}; "
            "spec=importlib.util.spec_from_file_location('schemas_candidate_check', p); "
            "m=importlib.util.module_from_spec(spec); "
            "warnings.simplefilter('error'); spec.loader.exec_module(m); "
            "from pydantic import BaseModel; "
            "[(o.model_json_schema()) for o in vars(m).values() "
            "if inspect.isclass(o) and o.__module__==m.__name__ and issubclass(o, BaseModel)]; "
            "print('SCHEMAS_CANDIDATE_IMPORT_OK')"
        )
        result = _run([sys.executable, "-c", code], Path(td))
        if result.returncode != 0 or "SCHEMAS_CANDIDATE_IMPORT_OK" not in result.stdout:
            raise RuntimeError("Candidate import/schema validation failed:\n" + result.stdout)


def main() -> int:
    repo_root = Path.cwd()
    source = repo_root / "wa_backend" / "schemas.py"
    if not source.is_file():
        print("ERROR: Run this from the Wanasah repository root; wa_backend/schemas.py was not found.")
        return 2

    original = source.read_bytes()
    normalized = _normalize_lf(original)
    actual_sha = _git_blob_sha(normalized)
    if actual_sha != EXPECTED_NORMALIZED_GIT_BLOB_SHA:
        print("ERROR: Local wa_backend/schemas.py is not the exact audited GitHub base.")
        print(f"Expected normalized Git blob SHA: {EXPECTED_NORMALIZED_GIT_BLOB_SHA}")
        print(f"Actual normalized Git blob SHA:   {actual_sha}")
        print("No patch was generated and schemas.py was NOT modified.")
        return 3

    candidate_lf = zlib.decompress(base64.b85decode(_CANDIDATE_PAYLOAD.encode("ascii")))
    _validate_candidate(candidate_lf)

    newline = b"\r\n" if b"\r\n" in original else b"\n"
    candidate = candidate_lf if newline == b"\n" else candidate_lf.replace(b"\n", b"\r\n")

    patch_path = repo_root / PATCH_NAME
    with tempfile.TemporaryDirectory(prefix="wanasah_schemas_patch_") as td:
        temp_root = Path(td)
        _git_init_with_base(temp_root, original)
        (temp_root / "wa_backend" / "schemas.py").write_bytes(candidate)
        result = subprocess.run(
            ["git", "diff", "--binary", "--", "wa_backend/schemas.py"],
            cwd=temp_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.startswith(b"diff --git"):
            error_text = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError("Git failed to generate a valid patch:\n" + error_text)
        # Preserve CR bytes in patch context when the Windows checkout uses CRLF.
        patch_path.write_bytes(result.stdout)

    # Verify against a fresh copy of the exact local file before handing the patch to the user.
    with tempfile.TemporaryDirectory(prefix="wanasah_schemas_verify_") as td:
        verify_root = Path(td)
        _git_init_with_base(verify_root, original)
        check = _run(["git", "apply", "--check", str(patch_path)], verify_root)
        if check.returncode != 0:
            raise RuntimeError("Generated patch failed git apply --check:\n" + check.stdout)
        apply = _run(["git", "apply", str(patch_path)], verify_root)
        if apply.returncode != 0:
            raise RuntimeError("Generated patch failed to apply:\n" + apply.stdout)
        if (verify_root / "wa_backend" / "schemas.py").read_bytes() != candidate:
            raise RuntimeError("Generated patch applied but the result did not match the audited candidate.")

    if source.read_bytes() != original:
        raise RuntimeError("Safety failure: schemas.py changed during patch generation.")

    print("SCHEMAS_PATCH_READY")
    print(f"Base Git blob SHA: {EXPECTED_NORMALIZED_GIT_BLOB_SHA}")
    print(f"Patch: {patch_path}")
    print("schemas.py was NOT modified.")
    print("Next:")
    print(f"  git apply --check {PATCH_NAME}")
    print(f"  git apply {PATCH_NAME}")
    print("  python -m py_compile wa_backend/schemas.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
