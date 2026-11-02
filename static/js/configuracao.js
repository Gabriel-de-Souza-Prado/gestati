"use strict";
const finalidade = document.getElementById("id_tipo");
if (finalidade) {
    const atualizar = () => {
        const correcao = finalidade.value === "correcao";
        const camposCorrecao = document.getElementById("correcao-fields");
        const camposFisica = document.getElementById("fisica-fields");
        camposCorrecao.hidden = camposCorrecao.disabled = !correcao;
        camposFisica.hidden = camposFisica.disabled = correcao;
    };
    finalidade.addEventListener("change", atualizar);
    atualizar();
}
