// Соло-екран: підказки, «ще підказка», guess, heat, результат.
// Власник: Андрій.
//
// Поки що лише карта: клік по області → ID у консолі та обвідка. Логіку раунду додамо на етапі 2.

import { getGeo } from './api.js';
import { createMap } from './map.js';

const geo = await getGeo();
const map = createMap(document.getElementById('map'), geo, {
  onClick: (regionId) => {
    console.log('click', regionId);
    map.select(regionId);
  },
});
